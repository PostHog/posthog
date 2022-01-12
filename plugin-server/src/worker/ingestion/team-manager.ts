import { Properties } from '@posthog/plugin-scaffold'
import { StatsD } from 'hot-shots'
import LRU from 'lru-cache'
import { DateTime } from 'luxon'

import { ONE_HOUR } from '../../config/constants'
import {
    DateTimePropertyTypeFormat,
    PluginsServerConfig,
    PropertyType,
    PropertyTypeFormat,
    Team,
    TeamId,
    UnixTimestampPropertyTypeFormat,
} from '../../types'
import { DB } from '../../utils/db/db'
import { timeoutGuard } from '../../utils/db/utils'
import { posthog } from '../../utils/posthog'
import { status } from '../../utils/status'
import { getByAge, UUIDT } from '../../utils/utils'

type TeamCache<T> = Map<TeamId, [T, number]>

export const unixTimestampPropertyTypeFormatPatterns: Record<UnixTimestampPropertyTypeFormat, RegExp> = {
    unix_timestamp: /^\d{10}(\.\d*)?$/,
    unix_timestamp_milliseconds: /^\d{13}$/,
}

export const dateTimePropertyTypeFormatPatterns: Record<DateTimePropertyTypeFormat, RegExp> = {
    'YYYY-MM-DD': /^\d{4}-\d{2}-\d{2}$/,
    'YYYY-MM-DDThh:mm:ssZ': /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/,
    'YYYY-MM-DD hh:mm:ss': /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/,
    'DD-MM-YYYY hh:mm:ss': /^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}$/,
    'DD/MM/YYYY hh:mm:ss': /^\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}:\d{2}$/,
    'YYYY/MM/DD hh:mm:ss': /^\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}:\d{2}$/,
    rfc_822:
        /^((mon|tue|wed|thu|fri|sat|sun), )?\d{2} (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec) \d{4} \d{2}:\d{2}:\d{2}( [+|-]\d{4})?$/i,
}

function detectPropertyDefinitionTypes(value: unknown, key: string) {
    let propertyType: PropertyType | null = null
    let propertyTypeFormat: PropertyTypeFormat | null = null

    /**
     * Auto detecting unix timestamps is tricky. It's hard to know what is a big number or ID and what is a timestamp
     *
     * This tries to detect the most likely cases.
     *
     * * Numbers or Numeric Strings
     * * That are either ten digits (seconds since unix epoch), or 13 digits (milliseconds since unix epoch),
     * * or ten digits with numbers after the decimal place (whole seconds since unix epoch and fractions of a second)
     * * where the property key includes either time or timestamp
     *
     * ten digits of seconds since epoch runs between Sep 09 2001 and Nov 20th 2286
     *
     * These are some representations from a variety of programming languages
     *
     * Python
     * >>> datetime.now().timestamp()
     * 1641477529.234715
     *
     * Ruby
     * puts Time.now.to_i
     * 1641477692
     *
     * Node JS
     * console.log(Date.now())
     * 1641477753371
     *
     * Java
     * System.out.println(LocalDateTime.now().toEpochSecond(ZoneOffset.UTC));
     * 1641478115
     *
     * SQL Lite
     * select strftime('%s', 'now')
     * 1641478347
     */
    const detectUnixTimestamps = () => {
        Object.entries(unixTimestampPropertyTypeFormatPatterns).find(([dateTimeFormat, pattern]) => {
            if (
                (key.toLowerCase().includes('timestamp') || key.toLowerCase().includes('time')) &&
                String(value).match(pattern)
            ) {
                propertyType = PropertyType.DateTime
                propertyTypeFormat = dateTimeFormat as PropertyTypeFormat
                return true
            }
        })
    }

    if (typeof value === 'number') {
        propertyType = PropertyType.Numeric

        detectUnixTimestamps()
    }

    if (typeof value === 'string') {
        propertyType = PropertyType.String

        Object.entries(dateTimePropertyTypeFormatPatterns).find(([dateTimeFormat, pattern]) => {
            if (value.match(pattern)) {
                propertyType = PropertyType.DateTime
                propertyTypeFormat = dateTimeFormat as PropertyTypeFormat
                return true
            }
        })

        detectUnixTimestamps()
    }

    return { propertyType, propertyTypeFormat }
}

export class TeamManager {
    db: DB
    teamCache: TeamCache<Team | null>
    eventDefinitionsCache: Map<TeamId, Set<string>>
    eventPropertiesCache: LRU<string, Set<string>> // Map<JSON.stringify([TeamId, Event], Set<Property>>
    eventLastSeenCache: LRU<string, number> // key: JSON.stringify([team_id, event]); value: parseInt(YYYYMMDD)
    propertyDefinitionsCache: Map<TeamId, Set<string>>
    instanceSiteUrl: string
    experimentalLastSeenAtEnabled: boolean
    experimentalEventPropertyTrackerEnabled: boolean
    statsd?: StatsD

    constructor(db: DB, serverConfig: PluginsServerConfig, statsd?: StatsD) {
        this.db = db
        this.statsd = statsd
        this.teamCache = new Map()
        this.eventDefinitionsCache = new Map()
        this.eventPropertiesCache = new LRU({
            max: serverConfig.EVENT_PROPERTY_LRU_SIZE, // keep in memory the last 10k team+event combos we have seen
            maxAge: ONE_HOUR * 24, // cache up to 24h
            updateAgeOnGet: true,
        })
        this.eventLastSeenCache = new LRU({
            max: serverConfig.EVENT_PROPERTY_LRU_SIZE, // keep in memory the last 10k team+event combos we have seen
            maxAge: ONE_HOUR * 24, // cache up to 24h
            updateAgeOnGet: true,
        })
        this.propertyDefinitionsCache = new Map()
        this.instanceSiteUrl = serverConfig.SITE_URL || 'unknown'

        // TODO: #7422 Remove temporary EXPERIMENTAL_EVENTS_LAST_SEEN_ENABLED
        this.experimentalLastSeenAtEnabled = serverConfig.EXPERIMENTAL_EVENTS_LAST_SEEN_ENABLED ?? false

        // TODO: #7500 Remove temporary EXPERIMENTAL_EVENT_PROPERTY_TRACKER_ENABLED
        this.experimentalEventPropertyTrackerEnabled = serverConfig.EXPERIMENTAL_EVENT_PROPERTY_TRACKER_ENABLED ?? false
    }

    public async fetchTeam(teamId: number): Promise<Team | null> {
        const cachedTeam = getByAge(this.teamCache, teamId)
        if (cachedTeam) {
            return cachedTeam
        }

        const timeout = timeoutGuard(`Still running "fetchTeam". Timeout warning after 30 sec!`)
        try {
            const team: Team | null = (await this.db.fetchTeam(teamId)) || null
            this.teamCache.set(teamId, [team, Date.now()])
            return team
        } finally {
            clearTimeout(timeout)
        }
    }

    public async updateEventNamesAndProperties(teamId: number, event: string, properties: Properties): Promise<void> {
        const startTime = DateTime.now()
        const team: Team | null = await this.fetchTeam(teamId)

        if (!team) {
            return
        }

        const timeout = timeoutGuard('Still running "updateEventNamesAndProperties". Timeout warning after 30 sec!', {
            event: event,
            ingested: team.ingested_event,
        })

        await this.cacheEventNamesAndProperties(team.id, event)
        await this.syncEventDefinitions(team, event)
        await this.syncEventProperties(team, event, Object.keys(properties))
        await this.syncPropertyDefinitions(properties, team)
        await this.setTeamIngestedEvent(team, properties)

        clearTimeout(timeout)

        const statsDEvent = this.experimentalLastSeenAtEnabled
            ? 'updateEventNamesAndProperties.lastSeenAtEnabled'
            : 'updateEventNamesAndProperties'
        this.statsd?.timing(statsDEvent, DateTime.now().diff(startTime).as('milliseconds'))
    }

    private async syncEventDefinitions(team: Team, event: string) {
        const cacheKey = JSON.stringify([team.id, event])
        const cacheTime = parseInt(DateTime.now().toFormat('yyyyMMdd', { timeZone: 'UTC' }))

        if (!this.eventDefinitionsCache.get(team.id)?.has(event)) {
            // TODO: #7422 Temporary conditional to test experimental feature
            if (this.experimentalLastSeenAtEnabled) {
                status.info('Inserting new event definition with last_seen_at')
                this.eventLastSeenCache.set(cacheKey, cacheTime)
                await this.db.postgresQuery(
                    `INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id, last_seen_at, created_at)` +
                        ` VALUES ($1, $2, NULL, NULL, $3, $4, NOW())` +
                        ` ON CONFLICT ON CONSTRAINT posthog_eventdefinition_team_id_name_80fa0b87_uniq` +
                        ` DO UPDATE SET last_seen_at=$4`,
                    [new UUIDT().toString(), event, team.id, DateTime.now()],
                    'insertEventDefinition'
                )
            } else {
                await this.db.postgresQuery(
                    `INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id, created_at)` +
                        ` VALUES ($1, $2, NULL, NULL, $3, NOW())` +
                        ` ON CONFLICT DO NOTHING`,
                    [new UUIDT().toString(), event, team.id],
                    'insertEventDefinition'
                )
            }
            this.eventDefinitionsCache.get(team.id)?.add(event)
        } else {
            // TODO: #7422 Temporary conditional to test experimental feature
            if (this.experimentalLastSeenAtEnabled) {
                if ((this.eventLastSeenCache.get(cacheKey) ?? 0) < cacheTime) {
                    this.eventLastSeenCache.set(cacheKey, cacheTime)
                    await this.db.postgresQuery(
                        `UPDATE posthog_eventdefinition SET last_seen_at=$1 WHERE team_id=$2 and name=$3`,
                        [DateTime.now(), team.id, event],
                        'updateEventLastSeenAt'
                    )
                }
            }
        }
    }

    private async syncEventProperties(team: Team, event: string, propertyKeys: string[]) {
        if (!this.experimentalEventPropertyTrackerEnabled) {
            return
        }
        const key = JSON.stringify([team.id, event])
        let properties = this.eventPropertiesCache.get(key)
        if (!properties) {
            properties = new Set()
            this.eventPropertiesCache.set(key, properties)
        }
        for (const property of propertyKeys) {
            if (!properties.has(property)) {
                properties.add(property)
                await this.db.postgresQuery(
                    `INSERT INTO posthog_eventproperty (event, property, team_id) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING`,
                    [event, property, team.id],
                    'insertEventProperty'
                )
            }
        }
    }

    private async syncPropertyDefinitions(properties: Properties, team: Team) {
        for (const [key, value] of Object.entries(properties)) {
            if (!this.propertyDefinitionsCache.get(team.id)?.has(key)) {
                const isNumerical = typeof value === 'number'
                const { propertyType, propertyTypeFormat } = detectPropertyDefinitionTypes(value, key)

                await this.db.postgresQuery(
                    `
INSERT INTO posthog_propertydefinition
(id, name, is_numerical, volume_30_day, query_usage_30_day, team_id, property_type, property_type_format)
VALUES ($1, $2, $3, NULL, NULL, $4, $5, $6)
ON CONFLICT ON CONSTRAINT posthog_propertydefinition_team_id_name_e21599fc_uniq
DO UPDATE SET property_type=$5, property_type_format=$6 where posthog_propertydefinition.property_type is null`,
                    [new UUIDT().toString(), key, isNumerical, team.id, propertyType, propertyTypeFormat],
                    'insertPropertyDefinition'
                )
                this.propertyDefinitionsCache.get(team.id)?.add(key)
            }
        }
    }

    private async setTeamIngestedEvent(team: Team, properties: Properties) {
        if (team && !team.ingested_event) {
            await this.db.postgresQuery(
                `UPDATE posthog_team SET ingested_event = $1 WHERE id = $2`,
                [true, team.id],
                'setTeamIngestedEvent'
            )

            // First event for the team captured
            const organizationMembers = await this.db.postgresQuery(
                'SELECT distinct_id FROM posthog_user JOIN posthog_organizationmembership ON posthog_user.id = posthog_organizationmembership.user_id WHERE organization_id = $1',
                [team.organization_id],
                'posthog_organizationmembership'
            )
            const distinctIds: { distinct_id: string }[] = organizationMembers.rows
            for (const { distinct_id } of distinctIds) {
                posthog.identify(distinct_id)
                posthog.capture('first team event ingested', {
                    team: team.uuid,
                    sdk: properties.$lib,
                    realm: properties.realm,
                    host: properties.$host,
                    $groups: {
                        project: team.uuid,
                        organization: team.organization_id,
                        instance: this.instanceSiteUrl,
                    },
                })
            }
        }
    }

    public async cacheEventNamesAndProperties(teamId: number, event: string): Promise<void> {
        let eventDefinitionsCache = this.eventDefinitionsCache.get(teamId)
        if (!eventDefinitionsCache) {
            const eventNames = await this.db.postgresQuery(
                'SELECT name FROM posthog_eventdefinition WHERE team_id = $1',
                [teamId],
                'fetchEventDefinitions'
            )
            eventDefinitionsCache = new Set(eventNames.rows.map((r) => r.name))
            this.eventDefinitionsCache.set(teamId, eventDefinitionsCache)
        }

        let propertyDefinitionsCache = this.propertyDefinitionsCache.get(teamId)
        if (!propertyDefinitionsCache) {
            const eventProperties = await this.db.postgresQuery(
                'SELECT name FROM posthog_propertydefinition WHERE team_id = $1 and property_type is not null',
                [teamId],
                'fetchPropertyDefinitions'
            )
            propertyDefinitionsCache = new Set(eventProperties.rows.map((r) => r.name))
            this.propertyDefinitionsCache.set(teamId, propertyDefinitionsCache)
        }

        // Run only if the feature is enabled for this team
        if (this.experimentalEventPropertyTrackerEnabled) {
            const cacheKey = JSON.stringify([teamId, event])
            let properties = this.eventPropertiesCache.get(cacheKey)
            if (!properties) {
                properties = new Set()
                this.eventPropertiesCache.set(cacheKey, properties)

                // The code above and below introduces a race condition. At this point we have an empty set in the cache,
                // and will be waiting for the query below to return. If at the same time, asynchronously, we start to
                // process another event with the same name for this team, `syncEventProperties` above will see the empty
                // cache and will start to insert (on conflict do nothing) all the properties for the event. This will
                // continue until either 1) the inserts will fill up the cache, or 2) the query below returns.
                // All-in-all, not the end of the world, but a slight nuisance.

                const eventProperties = await this.db.postgresQuery(
                    'SELECT property FROM posthog_eventproperty WHERE team_id = $1 and event = $2',
                    [teamId, event],
                    'fetchEventProperties'
                )
                for (const { property } of eventProperties.rows) {
                    properties.add(property)
                }
            }
        }
    }
}
