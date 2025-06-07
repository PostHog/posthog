import { randomUUID } from 'crypto'
import { Message } from 'node-rdkafka'

import { insertRow } from '~/tests/helpers/sql'

import { ClickHouseTimestamp, ProjectId, RawClickHouseEvent, Team } from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
import { UUIDT } from '../../utils/utils'
import { CdpInternalEvent } from '../schema'
import {
    CyclotronJobInvocationHogFunction,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionType,
    IntegrationType,
} from '../types'

export const createHogFunction = (hogFunction: Partial<HogFunctionType>) => {
    const item: HogFunctionType = {
        id: randomUUID(),
        type: 'destination',
        name: 'Hog Function',
        team_id: 1,
        enabled: true,
        hog: '',
        bytecode: [],
        ...hogFunction,
    } as HogFunctionType

    return item
}

export const createIntegration = (integration: Partial<IntegrationType>) => {
    const item: IntegrationType = {
        team_id: 1,
        errors: '',
        created_at: new Date().toISOString(),
        created_by_id: 1001,
        id: integration.id ?? 1,
        kind: integration.kind ?? 'slack',
        config: {},
        sensitive_config: {},
        ...integration,
    }

    return item
}

export const createIncomingEvent = (teamId: number, data: Partial<RawClickHouseEvent>): RawClickHouseEvent => {
    return {
        team_id: teamId,
        project_id: teamId as ProjectId,
        created_at: new Date().toISOString() as ClickHouseTimestamp,
        elements_chain: '[]',
        person_created_at: new Date().toISOString() as ClickHouseTimestamp,
        person_properties: '{}',
        distinct_id: 'distinct_id_1',
        uuid: randomUUID(),
        event: '$pageview',
        timestamp: new Date().toISOString() as ClickHouseTimestamp,
        properties: '{}',
        person_mode: 'full',
        ...data,
    }
}

export const createKafkaMessage = (event: any, overrides: Partial<Message> = {}): Message => {
    return {
        partition: 1,
        topic: 'test',
        offset: 0,
        timestamp: overrides.timestamp ?? Date.now(),
        size: 1,
        ...overrides,
        value: Buffer.from(JSON.stringify(event)),
    }
}

export const createInternalEvent = (teamId: number, data: Partial<CdpInternalEvent>): CdpInternalEvent => {
    return {
        team_id: teamId,
        event: {
            timestamp: new Date().toISOString(),
            properties: {},
            uuid: randomUUID(),
            event: '$pageview',
            distinct_id: 'distinct_id',
        },
        ...data,
    }
}

export const insertHogFunction = async (
    postgres: PostgresRouter,
    team_id: Team['id'],
    hogFunction: Partial<HogFunctionType> = {}
): Promise<HogFunctionType> => {
    // This is only used for testing so we need to override some values

    const res = await insertRow(postgres, 'posthog_hogfunction', {
        ...createHogFunction({
            ...hogFunction,
            team_id: team_id,
        }),
        description: '',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        created_by_id: 1001,
        deleted: false,
    })
    return res
}

export const insertIntegration = async (
    postgres: PostgresRouter,
    team_id: Team['id'],
    integration: Partial<IntegrationType> = {}
): Promise<IntegrationType> => {
    const res = await insertRow(
        postgres,
        'posthog_integration',
        createIntegration({
            ...integration,
            team_id: team_id,
        })
    )
    return res
}

export const createHogExecutionGlobals = (
    data: Partial<HogFunctionInvocationGlobals> = {}
): HogFunctionInvocationGlobals => {
    return {
        groups: {},
        ...data,
        person: {
            id: 'uuid',
            name: 'test',
            url: 'http://localhost:8000/persons/1',
            properties: {
                email: 'test@posthog.com',
                first_name: 'Pumpkin',
            },
            ...(data.person ?? {}),
        },
        project: {
            id: 1,
            name: 'test',
            url: 'http://localhost:8000/projects/1',
            ...(data.project ?? {}),
        },
        event: {
            uuid: 'uuid',
            event: 'test',
            elements_chain: '',
            distinct_id: 'distinct_id',
            url: 'http://localhost:8000/events/1',
            properties: {
                $lib_version: '1.2.3',
            },
            timestamp: new Date().toISOString(),
            ...(data.event ?? {}),
        },
    }
}

export const createExampleInvocation = (
    _hogFunction: Partial<HogFunctionType> = {},
    _globals: Partial<HogFunctionInvocationGlobals> = {}
): CyclotronJobInvocationHogFunction => {
    const hogFunction = createHogFunction(_hogFunction)
    // Add the source of the trigger to the globals

    const globals = createHogExecutionGlobals(_globals)
    globals.source = {
        name: hogFunction.name ?? `Hog function: ${hogFunction.id}`,
        url: `${globals.project.url}/pipeline/destinations/hog-${hogFunction.id}/configuration/`,
    }

    return {
        id: new UUIDT().toString(),
        state: {
            globals: globals as HogFunctionInvocationGlobalsWithInputs,
            timings: [],
        },
        teamId: hogFunction.team_id,
        functionId: hogFunction.id,
        hogFunction,
        queue: 'hog',
        queuePriority: 0,
    }
}

const SAMPLE_GLOBALS = {
    event: {
        uuid: 'uuid',
        event: 'test',
        distinct_id: 'distinct_id',
        properties: {
            email: 'test@posthog.com',
        },
        elements_chain: '',
        timestamp: '',
        url: '',
    },
    project: {
        id: 1,
        name: 'test',
        url: 'http://localhost:8000/projects/1',
    },
}

export const createExampleSegmentInvocation = (
    _hogFunction: Partial<HogFunctionType> = {},
    inputs: Record<string, any> = {}
): CyclotronJobInvocationHogFunction => {
    const hogFunction = createHogFunction(_hogFunction)

    return {
        id: new UUIDT().toString(),
        state: {
            globals: {
                inputs,
                ...SAMPLE_GLOBALS,
            },
            timings: [],
        },
        teamId: hogFunction.team_id,
        functionId: hogFunction.id,
        hogFunction,
        queue: 'segment',
        queuePriority: 0,
    }
}

export const amplitudeInputs = {
    apiKey: 'api-key',
    user_id: 'user-id',
    secretKey: 'secret-key',
    device_id: 'device-id',
    endpoint: 'north_america',
    user_properties: {
        $os: 'Mac OS X',
        _kx: null,
        epik: null,
        test: 'abcdefge',
        $host: 'localhost:8010',
        dclid: null,
        email: 'max@posthog.com',
        gclid: null,
        qclid: null,
        realm: 'hosted-clickhouse',
        sccid: null,
        fbclid: null,
        gbraid: null,
        gclsrc: null,
        igshid: null,
        irclid: null,
        mc_cid: null,
        ttclid: null,
        twclid: null,
        wbraid: null,
        msclkid: null,
        rdt_cid: 'asdfsad',
        $browser: 'Chrome',
        utm_term: null,
        $pathname: '/project/1/activity/explore',
        $referrer:
            'http://localhost:8000/project/1/pipeline/new/destination/hog-template-meta-ads?showPaused=true&kind&search=meta',
        joined_at: '2025-04-04T11:33:18.022897+00:00',
        li_fat_id: null,
        strapi_id: null,
        gad_source: null,
        project_id: '01960093-a4e7-0000-8ff1-00a3c4b4207c',
        utm_medium: null,
        utm_source: null,
        $initial_os: 'Mac OS X',
        $os_version: '10.15.7',
        utm_content: null,
        $current_url: 'http://localhost:8000/project/1/activity/explore',
        $device_type: 'Desktop',
        $initial__kx: null,
        instance_tag: 'none',
        instance_url: 'http://localhost:8010',
        is_signed_up: true,
        utm_campaign: null,
        $initial_epik: null,
        $initial_host: 'localhost:8010',
        $screen_width: 2560,
        project_count: 1,
        $initial_dclid: null,
        $initial_gclid: null,
        $initial_qclid: null,
        $initial_sccid: null,
        $screen_height: 1440,
        $search_engine: 'google',
        anonymize_data: false,
        $geoip_latitude: -33.8715,
        $initial_fbclid: null,
        $initial_gbraid: null,
        $initial_gclsrc: null,
        $initial_igshid: null,
        $initial_irclid: null,
        $initial_mc_cid: null,
        $initial_ttclid: null,
        $initial_twclid: null,
        $initial_wbraid: null,
        $raw_user_agent:
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
        $viewport_width: 1698,
        has_social_auth: false,
        organization_id: '01960093-9cea-0000-8c9a-def990d34fbf',
        $browser_version: 135,
        $geoip_city_name: 'Sydney',
        $geoip_longitude: 151.2006,
        $geoip_time_zone: 'Australia/Sydney',
        $initial_browser: 'Chrome',
        $initial_msclkid: null,
        $initial_rdt_cid: null,
        $viewport_height: 1328,
        has_password_set: true,
        social_providers: [],
        $initial_pathname: '/organization/billing',
        $initial_referrer: '$direct',
        $initial_utm_term: null,
        $referring_domain: 'localhost:8000',
        is_email_verified: false,
        $geoip_postal_code: '2000',
        $initial_li_fat_id: null,
        organization_count: 1,
        $creator_event_uuid: '01960095-8a86-73c9-9adc-0d586ad50a6a',
        $geoip_country_code: 'AU',
        $geoip_country_name: 'Australia',
        $initial_gad_source: null,
        $initial_os_version: '15.2',
        $initial_utm_medium: null,
        $initial_utm_source: null,
        $initial_current_url: 'http://localhost:8010/organization/billing?cancel=true',
        $initial_device_type: 'Desktop',
        $initial_utm_content: null,
        $geoip_continent_code: 'OC',
        $geoip_continent_name: 'Oceania',
        $initial_screen_width: 2560,
        $initial_utm_campaign: null,
        team_member_count_all: 1,
        $geoip_accuracy_radius: 20,
        $geoip_city_confidence: null,
        $initial_screen_height: 1440,
        project_setup_complete: false,
        $initial_geoip_latitude: -33.8715,
        $initial_raw_user_agent:
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
        $initial_viewport_width: 1619,
        $initial_browser_version: 134,
        $initial_geoip_city_name: 'Sydney',
        $initial_geoip_longitude: 151.2006,
        $initial_geoip_time_zone: 'Australia/Sydney',
        $initial_viewport_height: 1328,
        $geoip_subdivision_1_code: 'NSW',
        $geoip_subdivision_1_name: 'New South Wales',
        $geoip_subdivision_2_code: null,
        $geoip_subdivision_2_name: null,
        $initial_referring_domain: '$direct',
        completed_onboarding_once: false,
        $initial_geoip_postal_code: '2000',
        has_seen_product_intro_for: {
            surveys: true,
        },
        $initial_geoip_country_code: 'AU',
        $initial_geoip_country_name: 'Australia',
        $initial_geoip_continent_code: 'OC',
        $initial_geoip_continent_name: 'Oceania',
        $initial_geoip_accuracy_radius: 20,
        $initial_geoip_city_confidence: null,
        $initial_geoip_subdivision_1_code: 'NSW',
        $initial_geoip_subdivision_1_name: 'New South Wales',
        $initial_geoip_subdivision_2_code: null,
        $initial_geoip_subdivision_2_name: null,
        current_organization_membership_level: 15,
    },
    groups: {},
    app_version: null,
    platform: 'Desktop',
    os_name: 'Mac OS X',
    os_version: '10.15.7',
    device_brand: '',
    device_manufacturer: null,
    device_model: null,
    carrier: '',
    country: 'Australia',
    region: '',
    city: 'Sydney',
    language: null,
    userAgent:
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
    userAgentParsing: true,
    includeRawUserAgent: false,
    utm_properties: {
        utm_term: null,
        utm_medium: null,
        utm_source: null,
        utm_content: null,
        utm_campaign: null,
    },
    referrer:
        'http://localhost:8000/project/1/pipeline/new/destination/hog-template-meta-ads?showPaused=true&kind&search=meta',
    library: 'web',
    userAgentData: {
        model: '',
        platformVersion: '',
    },
    internal_partner_action: 'logEventV2',
    debug_mode: true,
}

export const pipedriveResponse = {
    success: true,
    data: {
        id: 20,
        owner_id: {
            id: 1234,
            name: 'Max',
            email: 'max@posthog.com',
            has_pic: 0,
            pic_hash: null,
            active_flag: true,
            value: 1234,
        },
        org_id: null,
        name: 'Max',
        first_name: 'Max',
        last_name: null,
        open_deals_count: 0,
        related_open_deals_count: 0,
        closed_deals_count: 0,
        related_closed_deals_count: 0,
        participant_open_deals_count: 0,
        participant_closed_deals_count: 0,
        email_messages_count: 0,
        activities_count: 0,
        done_activities_count: 0,
        undone_activities_count: 0,
        files_count: 0,
        notes_count: 0,
        followers_count: 0,
        won_deals_count: 0,
        related_won_deals_count: 0,
        lost_deals_count: 0,
        related_lost_deals_count: 0,
        active_flag: true,
        phone: [{ value: '', primary: true }],
        email: [{ label: 'work', value: 'max@posthog.com', primary: true }],
        first_char: 'm',
        update_time: '2025-05-22 11:45:51',
        delete_time: null,
        add_time: '2025-05-22 11:45:51',
        visible_to: '3',
        picture_id: null,
        next_activity_date: null,
        next_activity_time: null,
        next_activity_id: null,
        last_activity_id: null,
        last_activity_date: null,
        last_incoming_mail_time: null,
        last_outgoing_mail_time: null,
        label: null,
        label_ids: [],
        im: [{ value: '', primary: true }],
        postal_address: null,
        postal_address_lat: null,
        postal_address_long: null,
        postal_address_subpremise: null,
        postal_address_street_number: null,
        postal_address_route: null,
        postal_address_sublocality: null,
        postal_address_locality: null,
        postal_address_admin_area_level_1: null,
        postal_address_admin_area_level_2: null,
        postal_address_country: null,
        postal_address_postal_code: null,
        postal_address_formatted_address: null,
        notes: null,
        birthday: null,
        job_title: null,
        org_name: null,
        cc_email: 'posthog-sandbox@pipedrivemail.com',
        primary_email: 'max@posthog.com',
        owner_name: 'Max',
        company_id: 1234,
    },
    additional_data: { didMerge: false },
    related_objects: {
        user: {
            '1234': {
                id: 1234,
                name: 'Max',
                email: 'max@posthog.com',
                has_pic: 0,
                pic_hash: null,
                active_flag: true,
            },
        },
    },
}
