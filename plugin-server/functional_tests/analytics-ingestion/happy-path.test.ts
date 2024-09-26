import { UUIDT } from '../../src/utils/utils'
import {
    capture,
    createOrganization,
    createTeam,
    fetchEvents,
    fetchGroups,
    fetchIngestionWarnings,
    fetchPersons,
    getMetric,
} from '../api'
import { waitForExpect } from '../expectations'

let organizationId: string

beforeAll(async () => {
    organizationId = await createOrganization()
})

test.concurrent(`event ingestion: handles $$client_ingestion_warning events`, async () => {
    const teamId = await createTeam(organizationId)
    const distinctId = new UUIDT().toString()

    await capture({
        teamId,
        distinctId,
        uuid: new UUIDT().toString(),
        event: '$$client_ingestion_warning',
        properties: {
            $$client_ingestion_warning_message: 'test message',
        },
    })

    await waitForExpect(async () => {
        const events = await fetchIngestionWarnings(teamId)
        expect(events).toEqual([
            expect.objectContaining({
                type: 'client_ingestion_warning',
                team_id: teamId,
                details: expect.objectContaining({ message: 'test message' }),
            }),
        ])
    })
})

test.concurrent(`event ingestion: can set and update group properties`, async () => {
    const teamId = await createTeam(organizationId)
    const distinctId = new UUIDT().toString()

    const groupIdentityUuid = new UUIDT().toString()
    await capture({
        teamId,
        distinctId,
        uuid: groupIdentityUuid,
        event: '$groupidentify',
        properties: {
            distinct_id: distinctId,
            $group_type: 'organization',
            $group_key: 'posthog',
            $group_set: {
                prop: 'value',
            },
        },
    })

    await waitForExpect(async () => {
        const group = await fetchGroups(teamId)
        expect(group).toEqual([
            expect.objectContaining({
                group_type_index: 0,
                group_key: 'posthog',
                group_properties: { prop: 'value' },
            }),
        ])
    })

    const firstEventUuid = new UUIDT().toString()
    await capture({
        teamId,
        distinctId,
        uuid: firstEventUuid,
        event: 'custom event',
        properties: {
            name: 'haha',
            $group_0: 'posthog',
        },
    })

    await waitForExpect(async () => {
        const [event] = await fetchEvents(teamId, firstEventUuid)
        expect(event).toEqual(
            expect.objectContaining({
                $group_0: 'posthog',
            })
        )
    })

    const secondGroupIdentityUuid = new UUIDT().toString()
    await capture({
        teamId,
        distinctId,
        uuid: secondGroupIdentityUuid,
        event: '$groupidentify',
        properties: {
            distinct_id: distinctId,
            $group_type: 'organization',
            $group_key: 'posthog',
            $group_set: {
                prop: 'updated value',
            },
        },
    })

    await waitForExpect(async () => {
        const group = await fetchGroups(teamId)
        expect(group).toContainEqual(
            expect.objectContaining({
                group_type_index: 0,
                group_key: 'posthog',
                group_properties: { prop: 'updated value' },
            })
        )
    })

    const secondEventUuid = new UUIDT().toString()
    await capture({
        teamId,
        distinctId,
        uuid: secondEventUuid,
        event: 'custom event',
        properties: {
            name: 'haha',
            $group_0: 'posthog',
        },
    })
    await waitForExpect(async () => {
        const [event] = await fetchEvents(teamId, secondEventUuid)
        expect(event).toEqual(
            expect.objectContaining({
                $group_0: 'posthog',
            })
        )
    })
})

test.concurrent(`liveness check endpoint works`, async () => {
    await waitForExpect(async () => {
        const response = await fetch('http://localhost:6738/_health')
        expect(response.status).toBe(200)

        const body = await response.json()
        expect(body).toEqual(
            expect.objectContaining({
                checks: expect.objectContaining({ 'analytics-ingestion': 'ok' }),
            })
        )
    })
})

test.concurrent(`event ingestion: handles $groupidentify with no properties`, async () => {
    const teamId = await createTeam(organizationId)
    const distinctId = new UUIDT().toString()

    const groupIdentityUuid = new UUIDT().toString()
    await capture({
        teamId,
        distinctId,
        uuid: groupIdentityUuid,
        event: '$groupidentify',
        properties: {
            distinct_id: distinctId,
            $group_type: 'organization',
            $group_key: 'posthog',
        },
    })

    const firstEventUuid = new UUIDT().toString()
    await capture({
        teamId,
        distinctId,
        uuid: firstEventUuid,
        event: 'custom event',
        properties: {
            name: 'haha',
            $group_0: 'posthog',
        },
    })

    const event = await waitForExpect(async () => {
        const [event] = await fetchEvents(teamId, firstEventUuid)
        expect(event).toBeDefined()
        return event
    })

    expect(event).toEqual(
        expect.objectContaining({
            $group_0: 'posthog',
        })
    )
})

test.concurrent(`event ingestion: can $set and update person properties`, async () => {
    const teamId = await createTeam(organizationId)
    const distinctId = new UUIDT().toString()

    await capture({
        teamId,
        distinctId,
        uuid: new UUIDT().toString(),
        event: '$identify',
        properties: {
            distinct_id: distinctId,
            $set: { prop: 'value' },
        },
    })

    const firstUuid = new UUIDT().toString()
    await capture({ teamId, distinctId, uuid: firstUuid, event: 'custom event', properties: {} })
    await waitForExpect(async () => {
        const [event] = await fetchEvents(teamId, firstUuid)
        expect(event).toEqual(
            expect.objectContaining({
                person_properties: expect.objectContaining({
                    prop: 'value',
                }),
            })
        )
    })

    await capture({
        teamId,
        distinctId,
        uuid: new UUIDT().toString(),
        event: '$identify',
        properties: {
            distinct_id: distinctId,
            $set: { prop: 'updated value' },
        },
    })

    const secondUuid = new UUIDT().toString()
    await capture({ teamId, distinctId, uuid: secondUuid, event: 'custom event', properties: {} })
    await waitForExpect(async () => {
        const [event] = await fetchEvents(teamId, secondUuid)
        expect(event).toEqual(
            expect.objectContaining({
                person_properties: expect.objectContaining({
                    prop: 'updated value',
                }),
            })
        )
    })
})

test.concurrent(
    `event ingestion: $process_person_profile=false drops expected fields, doesn't include person properties`,
    async () => {
        const teamId = await createTeam(organizationId)
        const distinctId = new UUIDT().toString()

        // Normal ("full") event creates person with a property.
        await capture({
            teamId,
            distinctId,
            uuid: new UUIDT().toString(),
            event: '$identify',
            properties: {
                distinct_id: distinctId,
                $set: { prop: 'value' },
            },
        })

        // Propertyless event tries to $set, $set_once, $unset and use groups, but none of these
        // should work.
        const properylessUuid = new UUIDT().toString()
        await capture({
            teamId,
            distinctId,
            uuid: properylessUuid,
            event: 'custom event',
            properties: {
                $process_person_profile: false,
                $group_0: 'group_key',
                $set: {
                    c: 3,
                },
                $set_once: {
                    d: 4,
                },
                $unset: ['prop'],
            },
            $set: {
                a: 1,
            },
            $set_once: {
                b: 2,
            },
        })
        await waitForExpect(async () => {
            const [event] = await fetchEvents(teamId, properylessUuid)
            expect(event).toEqual(
                expect.objectContaining({
                    person_properties: {},
                    properties: { uuid: properylessUuid, $sent_at: expect.any(String), $process_person_profile: false },
                    person_mode: 'propertyless',
                })
            )
        })

        // Another normal ("full") event sees the existing person property (it wasn't $unset)
        const secondUuid = new UUIDT().toString()
        await capture({ teamId, distinctId, uuid: secondUuid, event: 'custom event', properties: {} })
        await waitForExpect(async () => {
            const [event] = await fetchEvents(teamId, secondUuid)
            expect(event).toEqual(
                expect.objectContaining({
                    person_properties: expect.objectContaining({
                        prop: 'value',
                    }),
                    person_mode: 'full',
                })
            )
        })
    }
)

test.concurrent(`event ingestion: can $set and update person properties with top level $set`, async () => {
    // We support $set at the top level. This is as the time of writing how the
    // posthog-js library works.
    const teamId = await createTeam(organizationId)
    const distinctId = new UUIDT().toString()

    await capture({
        teamId,
        distinctId,
        uuid: new UUIDT().toString(),
        event: '$identify',
        properties: {
            distinct_id: distinctId,
        },
        $set: { prop: 'value' },
    })

    const firstUuid = new UUIDT().toString()
    await capture({ teamId, distinctId, uuid: firstUuid, event: 'custom event', properties: {} })
    await waitForExpect(async () => {
        const [event] = await fetchEvents(teamId, firstUuid)
        expect(event).toEqual(
            expect.objectContaining({
                person_properties: expect.objectContaining({
                    prop: 'value',
                }),
            })
        )
    })
})

test.concurrent(`event ingestion: person properties are point in event time`, async () => {
    const teamId = await createTeam(organizationId)
    const distinctId = new UUIDT().toString()

    await capture({
        teamId,
        distinctId,
        uuid: new UUIDT().toString(),
        event: '$identify',
        properties: {
            distinct_id: distinctId,
            $set: { prop: 'value' },
        },
    })

    const firstUuid = new UUIDT().toString()
    await capture({ teamId, distinctId, uuid: firstUuid, event: 'custom event', properties: {} })
    await capture({
        teamId,
        distinctId,
        uuid: new UUIDT().toString(),
        event: 'custom event',
        properties: {
            distinct_id: distinctId,
            $set: {
                prop: 'updated value',
                new_prop: 'new value',
            },
        },
    })

    await waitForExpect(async () => {
        const [event] = await fetchEvents(teamId, firstUuid)
        expect(event).toEqual(
            expect.objectContaining({
                person_properties: expect.objectContaining({
                    prop: 'value',
                }),
            })
        )
    })
})

test.concurrent(`event ingestion: can $set_once person properties but not update`, async () => {
    const teamId = await createTeam(organizationId)
    const distinctId = new UUIDT().toString()

    const personEventUuid = new UUIDT().toString()
    await capture({
        teamId,
        distinctId,
        uuid: personEventUuid,
        event: '$identify',
        properties: {
            distinct_id: distinctId,
            $set_once: { prop: 'value' },
        },
    })

    const firstUuid = new UUIDT().toString()
    await capture({ teamId, distinctId, uuid: firstUuid, event: 'custom event', properties: {} })
    await waitForExpect(async () => {
        const [event] = await fetchEvents(teamId, firstUuid)
        expect(event).toEqual(
            expect.objectContaining({
                person_properties: {
                    $creator_event_uuid: personEventUuid,
                    prop: 'value',
                    $initial_dclid: null,
                    $initial_fbclid: null,
                    $initial_gad_source: null,
                    $initial_gbraid: null,
                    $initial_gclid: null,
                    $initial_gclsrc: null,
                    $initial_igshid: null,
                    $initial_li_fat_id: null,
                    $initial_mc_cid: null,
                    $initial_msclkid: null,
                    $initial_rdt_cid: null,
                    $initial_ttclid: null,
                    $initial_twclid: null,
                    $initial_utm_campaign: null,
                    $initial_utm_content: null,
                    $initial_utm_medium: null,
                    $initial_utm_name: null,
                    $initial_utm_source: null,
                    $initial_utm_term: null,
                    $initial_wbraid: null,
                },
            })
        )
    })

    await capture({
        teamId,
        distinctId,
        uuid: personEventUuid,
        event: '$identify',
        properties: {
            distinct_id: distinctId,
            $set_once: { prop: 'updated value' },
        },
    })

    const secondUuid = new UUIDT().toString()
    await capture({ teamId, distinctId, uuid: secondUuid, event: 'custom event', properties: {} })
    await waitForExpect(async () => {
        const [event] = await fetchEvents(teamId, secondUuid)
        expect(event).toEqual(
            expect.objectContaining({
                person_properties: {
                    $creator_event_uuid: personEventUuid,
                    prop: 'value',
                },
            })
        )
    })
})

test.concurrent(
    `event ingestion: can $set_once person properties but not update, with top level $set_once`,
    async () => {
        // We support $set_once at the top level. This is as the time of writing
        // how the posthog-js library works.
        const teamId = await createTeam(organizationId)
        const distinctId = new UUIDT().toString()

        const personEventUuid = new UUIDT().toString()
        await capture({
            teamId,
            distinctId,
            uuid: personEventUuid,
            event: '$identify',
            properties: {
                distinct_id: distinctId,
            },
            $set_once: { prop: 'value' },
        })

        const firstUuid = new UUIDT().toString()
        await capture({ teamId, distinctId, uuid: firstUuid, event: 'custom event', properties: {} })
        await waitForExpect(async () => {
            const [event] = await fetchEvents(teamId, firstUuid)
            expect(event).toEqual(
                expect.objectContaining({
                    person_properties: {
                        $creator_event_uuid: personEventUuid,
                        prop: 'value',
                        $initial_dclid: null,
                        $initial_fbclid: null,
                        $initial_gad_source: null,
                        $initial_gbraid: null,
                        $initial_gclid: null,
                        $initial_gclsrc: null,
                        $initial_igshid: null,
                        $initial_li_fat_id: null,
                        $initial_mc_cid: null,
                        $initial_msclkid: null,
                        $initial_rdt_cid: null,
                        $initial_ttclid: null,
                        $initial_twclid: null,
                        $initial_utm_campaign: null,
                        $initial_utm_content: null,
                        $initial_utm_medium: null,
                        $initial_utm_name: null,
                        $initial_utm_source: null,
                        $initial_utm_term: null,
                        $initial_wbraid: null,
                    },
                })
            )
        })
    }
)

test.concurrent(`event ingestion: events without a team_id get processed correctly`, async () => {
    const token = new UUIDT().toString()
    const teamId = await createTeam(organizationId, '', token)
    const personIdentifier = 'test@posthog.com'

    await capture({
        teamId: null,
        distinctId: personIdentifier,
        uuid: new UUIDT().toString(),
        event: 'test event',
        properties: {
            distinct_id: personIdentifier,
        },
        token,
    })

    await waitForExpect(async () => {
        const events = await fetchEvents(teamId)
        expect(events.length).toBe(1)
        expect(events[0].team_id).toBe(teamId)
    })
})

test.concurrent('consumer updates timestamp exported to prometheus', async () => {
    // NOTE: it may be another event other than the one we emit here that causes
    // the gauge to increase, but pushing this event through should at least
    // ensure that the gauge is updated.
    const teamId = await createTeam(organizationId)
    const distinctId = new UUIDT().toString()

    const metricBefore = await getMetric({
        name: 'latest_processed_timestamp_ms',
        type: 'GAUGE',
        labels: { topic: 'events_plugin_ingestion', partition: '0', groupId: 'ingestion' },
    })

    await capture({ teamId, distinctId, uuid: new UUIDT().toString(), event: 'custom event', properties: {} })

    await waitForExpect(async () => {
        const metricAfter = await getMetric({
            name: 'latest_processed_timestamp_ms',
            type: 'GAUGE',
            labels: { topic: 'events_plugin_ingestion', partition: '0', groupId: 'ingestion' },
        })
        expect(metricAfter).toBeGreaterThan(metricBefore)
        expect(metricAfter).toBeLessThan(Date.now()) // Make sure, e.g. we're not setting micro seconds
        expect(metricAfter).toBeGreaterThan(Date.now() - 60_000) // Make sure, e.g. we're not setting seconds
    }, 10_000)
})

test.concurrent(`event ingestion: initial login flow keeps the same person_id`, async () => {
    const teamId = await createTeam(organizationId)
    const initialDistinctId = 'initialDistinctId'
    const personIdentifier = 'test@posthog.com'

    // This simulates initial sign-up flow,
    // where the user has first been browsing the site anonymously for a while

    // First we emit an anoymous event and wait for the person to be
    // created.
    const initialEventId = new UUIDT().toString()
    await capture({ teamId, distinctId: initialDistinctId, uuid: initialEventId, event: 'custom event' })
    await waitForExpect(async () => {
        const persons = await fetchPersons(teamId)
        expect(persons).toContainEqual(
            expect.objectContaining({
                properties: expect.objectContaining({ $creator_event_uuid: initialEventId }),
            })
        )
    }, 10000)

    // We then identify the person
    await capture({
        teamId,
        distinctId: personIdentifier,
        uuid: new UUIDT().toString(),
        event: '$identify',
        properties: {
            distinct_id: personIdentifier,
            $anon_distinct_id: initialDistinctId,
        },
    })

    await waitForExpect(async () => {
        const events = await fetchEvents(teamId)
        expect(events.length).toBe(2)
        expect(events[0].person_id).toBeDefined()
        expect(events[0].person_id).not.toBe('00000000-0000-0000-0000-000000000000')
        expect(new Set(events.map((event) => event.person_id)).size).toBe(1)
    }, 10000)
})

test.concurrent(`events still ingested even if merge fails`, async () => {
    const teamId = await createTeam(organizationId)
    const illegalDistinctId = '0'
    const distinctId = new UUIDT().toString()

    // First we emit anoymous events and wait for the persons to be created.
    await capture({ teamId, distinctId: illegalDistinctId, uuid: new UUIDT().toString(), event: 'custom event' })
    await capture({ teamId, distinctId: distinctId, uuid: new UUIDT().toString(), event: 'custom event 2' })

    await waitForExpect(async () => {
        const persons = await fetchPersons(teamId)
        expect(persons.length).toBe(2)
    }, 10000)

    await capture({
        teamId,
        distinctId: distinctId,
        uuid: new UUIDT().toString(),
        event: '$merge_dangerously',
        properties: {
            distinct_id: distinctId,
            alias: illegalDistinctId,
            $set: { prop: 'value' },
        },
    })

    await waitForExpect(async () => {
        const events = await fetchEvents(teamId)
        expect(events.length).toBe(3)
    }, 10000)

    await waitForExpect(async () => {
        const events = await fetchEvents(teamId)
        expect(events.length).toBe(3)
        expect(events[0].person_id).toBeDefined()
        expect(events[0].person_id).not.toBe('00000000-0000-0000-0000-000000000000')
        expect(new Set(events.map((event) => event.person_id)).size).toBe(2)
    }, 10000)
})

test.concurrent(`properties still $set even if merge fails`, async () => {
    const teamId = await createTeam(organizationId)
    const illegalDistinctId = '0'
    const distinctId = new UUIDT().toString()

    await capture({
        teamId,
        distinctId: distinctId,
        uuid: new UUIDT().toString(),
        event: '$merge_dangerously',
        properties: {
            distinct_id: distinctId,
            alias: illegalDistinctId,
            $set: { prop: 'value' },
        },
    })

    const firstUuid = new UUIDT().toString()
    await capture({ teamId, distinctId, uuid: firstUuid, event: 'custom event', properties: {} })
    await waitForExpect(async () => {
        const [event] = await fetchEvents(teamId, firstUuid)
        expect(event).toEqual(
            expect.objectContaining({
                person_properties: expect.objectContaining({
                    prop: 'value',
                }),
            })
        )
    })
})

test.concurrent(`single merge results in all events resolving to the same person id`, async () => {
    const teamId = await createTeam(organizationId)
    const initialDistinctId = new UUIDT().toString()
    const secondDistinctId = new UUIDT().toString()
    const personIdentifier = new UUIDT().toString()

    // This simulates sign-up flow with backend events having an anonymous ID in both frontend and backend

    // First we emit anoymous events and wait for the persons to be created.
    const initialEventId = new UUIDT().toString()
    await capture({ teamId, distinctId: initialDistinctId, uuid: initialEventId, event: 'custom event' })
    const secondEventId = new UUIDT().toString()
    await capture({ teamId, distinctId: secondDistinctId, uuid: secondEventId, event: 'custom event 2' })
    await waitForExpect(async () => {
        const persons = await fetchPersons(teamId)
        expect(persons).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    properties: expect.objectContaining({ $creator_event_uuid: initialEventId }),
                }),
                expect.objectContaining({
                    properties: expect.objectContaining({ $creator_event_uuid: secondEventId }),
                }),
            ])
        )
    }, 10000)

    // Then we identify both ids
    const uuidOfFirstIdentifyEvent = new UUIDT().toString()
    await capture({
        teamId,
        distinctId: personIdentifier,
        uuid: uuidOfFirstIdentifyEvent,
        event: '$identify',
        properties: {
            distinct_id: personIdentifier,
            $anon_distinct_id: initialDistinctId,
        },
    })
    const uuidOfSecondIdentifyEvent = new UUIDT().toString()
    await capture({
        teamId,
        distinctId: personIdentifier,
        uuid: uuidOfSecondIdentifyEvent,
        event: '$identify',
        properties: {
            distinct_id: personIdentifier,
            $anon_distinct_id: secondDistinctId,
        },
    })

    await waitForExpect(async () => {
        const events = await fetchEvents(teamId)
        expect(events.length).toBe(4)
        expect(events[0].person_id).toBeDefined()
        expect(events[0].person_id).not.toBe('00000000-0000-0000-0000-000000000000')
        expect(new Set(events.map((event) => event.person_id)).size).toBe(1)
    }, 10000)
})

test.concurrent(`chained merge results in all events resolving to the same person id`, async () => {
    const teamId = await createTeam(organizationId)
    const initialDistinctId = new UUIDT().toString()
    const secondDistinctId = new UUIDT().toString()
    const thirdDistinctId = new UUIDT().toString()

    // First we emit anoymous events and wait for the persons to be created.
    await capture({ teamId, distinctId: initialDistinctId, uuid: new UUIDT().toString(), event: 'custom event' })
    await capture({ teamId, distinctId: secondDistinctId, uuid: new UUIDT().toString(), event: 'custom event 2' })
    await capture({ teamId, distinctId: thirdDistinctId, uuid: new UUIDT().toString(), event: 'custom event 3' })
    await waitForExpect(async () => {
        const persons = await fetchPersons(teamId)
        expect(persons.length).toBe(3)
    }, 10000)

    // Then we identify first two together
    await capture({
        teamId,
        distinctId: initialDistinctId,
        uuid: new UUIDT().toString(),
        event: '$identify',
        properties: {
            distinct_id: initialDistinctId,
            $anon_distinct_id: secondDistinctId,
        },
    })

    // This guarantees that we process them in order, which verifies the right overrides and
    // makes sure we don't run into Merge refused errors if secondDistinctId is already identified if later completed first
    await waitForExpect(async () => {
        const persons = await fetchEvents(teamId)
        expect(persons.length).toBe(4)
    }, 10000)

    // Then we merge the third person
    await capture({
        teamId,
        distinctId: secondDistinctId,
        uuid: new UUIDT().toString(),
        event: '$identify',
        properties: {
            distinct_id: secondDistinctId,
            $anon_distinct_id: thirdDistinctId,
        },
    })

    await waitForExpect(async () => {
        const events = await fetchEvents(teamId)
        expect(events.length).toBe(5)
        expect(events[0].person_id).toBeDefined()
        expect(events[0].person_id).not.toBe('00000000-0000-0000-0000-000000000000')
        expect(new Set(events.map((event) => event.person_id)).size).toBe(1)
    }, 20000)
})

test.concurrent(`complex chained merge adds results in all events resolving to the same person id`, async () => {
    // let's assume we have 4 persons 1234, we'll first merge 1-2 & 3-4, then we'll merge 2-3
    // this should still result in all events having the same person_id or override[person_id]

    const teamId = await createTeam(organizationId)
    const initialDistinctId = new UUIDT().toString()
    const secondDistinctId = new UUIDT().toString()
    const thirdDistinctId = new UUIDT().toString()
    const forthDistinctId = new UUIDT().toString()

    // First we emit anoymous events and wait for the persons to be created.
    await capture({ teamId, distinctId: initialDistinctId, uuid: new UUIDT().toString(), event: 'custom event' })
    await capture({ teamId, distinctId: secondDistinctId, uuid: new UUIDT().toString(), event: 'custom event 2' })
    await capture({ teamId, distinctId: thirdDistinctId, uuid: new UUIDT().toString(), event: 'custom event 3' })
    await capture({ teamId, distinctId: forthDistinctId, uuid: new UUIDT().toString(), event: 'custom event 3' })
    await waitForExpect(async () => {
        const persons = await fetchPersons(teamId)
        expect(persons.length).toBe(4)
    }, 10000)

    // Then we identify 1-2 and 3-4
    await capture({
        teamId,
        distinctId: initialDistinctId,
        uuid: new UUIDT().toString(),
        event: '$identify',
        properties: {
            distinct_id: initialDistinctId,
            $anon_distinct_id: secondDistinctId,
        },
    })
    await capture({
        teamId,
        distinctId: thirdDistinctId,
        uuid: new UUIDT().toString(),
        event: '$identify',
        properties: {
            distinct_id: thirdDistinctId,
            $anon_distinct_id: forthDistinctId,
        },
    })

    await waitForExpect(async () => {
        const events = await fetchEvents(teamId)
        expect(events.length).toBe(6)
    }, 10000)

    // Then we merge 2-3
    await capture({
        teamId,
        distinctId: initialDistinctId,
        uuid: new UUIDT().toString(),
        event: '$merge_dangerously',
        properties: {
            distinct_id: secondDistinctId,
            alias: thirdDistinctId,
        },
    })

    await waitForExpect(async () => {
        const events = await fetchEvents(teamId)
        expect(events.length).toBe(7)
        expect(events[0].person_id).toBeDefined()
        expect(events[0].person_id).not.toBe('00000000-0000-0000-0000-000000000000')
        expect(new Set(events.map((event) => event.person_id)).size).toBe(1)
    }, 20000)
})

// TODO: adjust this test to poEEmbraceJoin
test.skip(`person properties don't see properties from descendents`, async () => {
    // The only thing that should propagate to an ancestor is the person_id.
    // Person properties should not propagate to ancestors within a branch.
    //
    //         P(k: v, set_once_property: value)
    //                        |
    //                        |
    //      P'(k: v, j: w, set_once_property: value)
    //
    // The person properties of P' should not be assiciated with events tied to
    // P.

    const teamId = await createTeam(organizationId)
    const firstDistinctId = new UUIDT().toString()

    const firstUuid = new UUIDT().toString()
    await capture({
        teamId,
        distinctId: firstDistinctId,
        uuid: firstUuid,
        event: 'custom event',
        properties: {
            $set: {
                k: 'v',
            },
            $set_once: {
                set_once_property: 'value',
            },
        },
    })

    const secondUuid = new UUIDT().toString()
    await capture({
        teamId,
        distinctId: firstDistinctId,
        uuid: secondUuid,
        event: 'custom event',
        properties: {
            $set: {
                j: 'w',
            },
            $set_once: {
                set_once_property: 'second value',
            },
        },
    })

    await waitForExpect(async () => {
        const [first] = await fetchEvents(teamId, firstUuid)
        const [second] = await fetchEvents(teamId, secondUuid)

        expect(first).toEqual(
            expect.objectContaining({
                person_id: second.person_id,
                person_properties: {
                    $creator_event_uuid: expect.any(String),
                    k: 'v',
                    set_once_property: 'value',
                },
            })
        )

        expect(second).toEqual(
            expect.objectContaining({
                person_properties: {
                    $creator_event_uuid: expect.any(String),
                    k: 'v',
                    j: 'w',
                    set_once_property: 'value',
                },
            })
        )
    })
})

// Skipping this test as without ording of events across distinct_id we don't
// know which event will be processed first, and hence this test is flaky. We
// are at any rate looking at alternatives to the implementation to speed up
// queries which may make this test obsolete.
test.skip(`person properties can't see properties from merge descendants`, async () => {
    // This is specifically to test that the merge event doesn't result in
    // properties being picked up on events from it's parents.
    //
    //             Alice(k: v)
    //                   \
    //                    \    Bob(j: w)
    //                     \   /
    //                      \ /
    //         AliceAndBob(k: v, j: w, l: x)
    //
    // NOTE: a stronger guarantee would be to ensure that events only pick up
    // properties from their relatives. Instead, if event e1 has a common
    // descendant with e2, they will pick up properties from which ever was
    // _processed_ first.
    // TODO: change the guarantee to be that unrelated branches properties are
    // isolated from each other.

    const teamId = await createTeam(organizationId)
    const aliceAnonId = new UUIDT().toString()
    const bobAnonId = new UUIDT().toString()

    const firstUuid = new UUIDT().toString()
    await capture({
        teamId,
        distinctId: aliceAnonId,
        uuid: firstUuid,
        event: 'custom event',
        properties: {
            $set: {
                k: 'v',
            },
        },
    })

    const secondUuid = new UUIDT().toString()
    await capture({
        teamId,
        distinctId: bobAnonId,
        uuid: secondUuid,
        event: 'custom event',
        properties: {
            $set: {
                j: 'w',
            },
        },
    })

    const thirdUuid = new UUIDT().toString()
    // NOTE: $create_alias is not symmetric, so we will get different
    // results according to the order of `bobAnonId` and `aliceAnonId`.
    await capture({
        teamId,
        distinctId: bobAnonId,
        uuid: thirdUuid,
        event: '$create_alias',
        properties: {
            alias: aliceAnonId,
            $set: {
                l: 'x',
            },
        },
    })

    // Now we wait to ensure that these events have been ingested.
    const [first, second, third] = await waitForExpect(async () => {
        const [first] = await fetchEvents(teamId, firstUuid)
        const [second] = await fetchEvents(teamId, secondUuid)
        const [third] = await fetchEvents(teamId, thirdUuid)

        expect(first).toBeDefined()
        expect(second).toBeDefined()
        expect(third).toBeDefined()

        return [first, second, third]
    })

    expect(first).toEqual(
        expect.objectContaining({
            person_id: third.person_id,
            person_properties: {
                $creator_event_uuid: expect.any(String),
                k: 'v',
            },
        })
    )

    expect(second).toEqual(
        expect.objectContaining({
            person_id: third.person_id,
            person_properties: {
                $creator_event_uuid: expect.any(String),
                k: 'v',
                j: 'w',
            },
        })
    )

    expect(third).toEqual(
        expect.objectContaining({
            person_properties: {
                $creator_event_uuid: expect.any(String),
                k: 'v',
                j: 'w',
                l: 'x',
            },
        })
    )
})
