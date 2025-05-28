import { DateTime, Settings } from 'luxon'

import { fetch, FetchResponse } from '~/src/utils/request'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import {
    amplitudeInputs,
    createExampleSegmentInvocation,
    insertHogFunction as _insertHogFunction,
    pipedriveResponse,
} from '../_tests/fixtures'
import { SEGMENT_DESTINATIONS_BY_ID } from '../segment/segment-templates'
import { HogFunctionType } from '../types'
import { CdpCyclotronWorkerSegment } from './cdp-cyclotron-segment-worker.consumer'

describe('CdpCyclotronWorkerSegment', () => {
    let processor: CdpCyclotronWorkerSegment
    let hub: Hub
    let team: Team
    let fn: HogFunctionType
    let mockFetch: jest.Mock<Promise<FetchResponse>, Parameters<typeof fetch>>

    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const item = await _insertHogFunction(hub.postgres, team.id, {
            ...hogFunction,
            type: 'destination',
        })
        // Trigger the reload that django would do
        processor['hogFunctionManager']['onHogFunctionsReloaded'](team.id, [item.id])
        return item
    }

    const amplitudePlugin = SEGMENT_DESTINATIONS_BY_ID['segment-amplitude']
    const amplitudeAction = amplitudePlugin.destination.actions['logEventV2']

    const pipedrivePlugin = SEGMENT_DESTINATIONS_BY_ID['segment-pipedrive']
    const pipedriveAction = pipedrivePlugin.destination.actions['createUpdatePerson']

    beforeEach(async () => {
        Settings.defaultZone = 'UTC'
        await resetTestDatabase()
        hub = await createHub()

        team = await getFirstTeam(hub)
        processor = new CdpCyclotronWorkerSegment(hub)

        await processor.start()

        processor['segmentPluginExecutor'].fetch = mockFetch = jest.fn((_url, _options) =>
            Promise.resolve({
                status: 200,
                json: () => Promise.resolve({}),
                text: () => Promise.resolve(JSON.stringify({})),
                headers: {},
            } as any)
        )

        jest.spyOn(processor['cyclotronJobQueue']!, 'queueInvocationResults').mockImplementation(() =>
            Promise.resolve()
        )

        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
    })

    afterEach(async () => {
        Settings.defaultZone = 'system'
        await processor.stop()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('segment plugins', () => {
        it('should call the plugin perform method', async () => {
            jest.spyOn(amplitudeAction as any, 'perform')

            fn = await insertHogFunction({
                name: 'Plugin test',
                template_id: 'segment-amplitude',
            })

            const invocation = createExampleSegmentInvocation(fn, amplitudeInputs)

            mockFetch.mockResolvedValue({
                status: 200,
                json: () => Promise.resolve({ total_count: 1 }),
                text: () =>
                    Promise.resolve(
                        JSON.stringify({
                            code: 200,
                            server_upload_time: 1747910402315,
                            payload_size_bytes: 22207,
                            events_ingested: 1,
                        })
                    ),
                headers: {},
            })

            const { invocationResults } = await processor.processBatch([invocation])

            expect(invocationResults.length).toBe(1)

            invocationResults[0].logs.forEach((x) => {
                if (typeof x.message === 'string' && x.message.includes('Function completed in')) {
                    x.message = 'Function completed in [REPLACED]'
                }
            })

            expect(invocationResults[0].logs).toMatchSnapshot()

            expect(amplitudeAction.perform).toHaveBeenCalledTimes(1)
            expect(forSnapshot(jest.mocked(amplitudeAction.perform!).mock.calls[0][1])).toMatchSnapshot()

            expect(mockFetch).toHaveBeenCalledTimes(1)
            expect(forSnapshot(mockFetch.mock.calls[0])).toMatchInlineSnapshot(`
                [
                  "https://api2.amplitude.com/2/httpapi",
                  {
                    "body": "{"api_key":"api-key","events":[{"os_name":"Mac OS X","os_version":"10.15.7","device_manufacturer":null,"device_model":null,"apiKey":"api-key","user_id":"user-id","secretKey":"secret-key","device_id":"device-id","endpoint":"north_america","user_properties":{"$os":"Mac OS X","_kx":null,"epik":null,"test":"abcdefge","$host":"localhost:8010","dclid":null,"email":"max@posthog.com","gclid":null,"qclid":null,"realm":"hosted-clickhouse","sccid":null,"fbclid":null,"gbraid":null,"gclsrc":null,"igshid":null,"irclid":null,"mc_cid":null,"ttclid":null,"twclid":null,"wbraid":null,"msclkid":null,"rdt_cid":"asdfsad","$browser":"Chrome","utm_term":null,"$pathname":"/project/1/activity/explore","$referrer":"http://localhost:8000/project/1/pipeline/new/destination/hog-template-meta-ads?showPaused=true&kind&search=meta","joined_at":"2025-04-04T11:33:18.022897+00:00","li_fat_id":null,"strapi_id":null,"gad_source":null,"project_id":"<REPLACED-UUID-0>","utm_medium":null,"utm_source":null,"$initial_os":"Mac OS X","$os_version":"10.15.7","utm_content":null,"$current_url":"http://localhost:8000/project/1/activity/explore","$device_type":"Desktop","$initial__kx":null,"instance_tag":"none","instance_url":"http://localhost:8010","is_signed_up":true,"utm_campaign":null,"$initial_epik":null,"$initial_host":"localhost:8010","$screen_width":2560,"project_count":1,"$initial_dclid":null,"$initial_gclid":null,"$initial_qclid":null,"$initial_sccid":null,"$screen_height":1440,"$search_engine":"google","anonymize_data":false,"$geoip_latitude":-33.8715,"$initial_fbclid":null,"$initial_gbraid":null,"$initial_gclsrc":null,"$initial_igshid":null,"$initial_irclid":null,"$initial_mc_cid":null,"$initial_ttclid":null,"$initial_twclid":null,"$initial_wbraid":null,"$raw_user_agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36","$viewport_width":1698,"has_social_auth":false,"organization_id":"<REPLACED-UUID-1>","$browser_version":135,"$geoip_city_name":"Sydney","$geoip_longitude":151.2006,"$geoip_time_zone":"Australia/Sydney","$initial_browser":"Chrome","$initial_msclkid":null,"$initial_rdt_cid":null,"$viewport_height":1328,"has_password_set":true,"social_providers":[],"$initial_pathname":"/organization/billing","$initial_referrer":"$direct","$initial_utm_term":null,"$referring_domain":"localhost:8000","is_email_verified":false,"$geoip_postal_code":"2000","$initial_li_fat_id":null,"organization_count":1,"$creator_event_uuid":"<REPLACED-UUID-2>","$geoip_country_code":"AU","$geoip_country_name":"Australia","$initial_gad_source":null,"$initial_os_version":"15.2","$initial_utm_medium":null,"$initial_utm_source":null,"$initial_current_url":"http://localhost:8010/organization/billing?cancel=true","$initial_device_type":"Desktop","$initial_utm_content":null,"$geoip_continent_code":"OC","$geoip_continent_name":"Oceania","$initial_screen_width":2560,"$initial_utm_campaign":null,"team_member_count_all":1,"$geoip_accuracy_radius":20,"$geoip_city_confidence":null,"$initial_screen_height":1440,"project_setup_complete":false,"$initial_geoip_latitude":-33.8715,"$initial_raw_user_agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36","$initial_viewport_width":1619,"$initial_browser_version":134,"$initial_geoip_city_name":"Sydney","$initial_geoip_longitude":151.2006,"$initial_geoip_time_zone":"Australia/Sydney","$initial_viewport_height":1328,"$geoip_subdivision_1_code":"NSW","$geoip_subdivision_1_name":"New South Wales","$geoip_subdivision_2_code":null,"$geoip_subdivision_2_name":null,"$initial_referring_domain":"$direct","completed_onboarding_once":false,"$initial_geoip_postal_code":"2000","has_seen_product_intro_for":{"surveys":true},"$initial_geoip_country_code":"AU","$initial_geoip_country_name":"Australia","$initial_geoip_continent_code":"OC","$initial_geoip_continent_name":"Oceania","$initial_geoip_accuracy_radius":20,"$initial_geoip_city_confidence":null,"$initial_geoip_subdivision_1_code":"NSW","$initial_geoip_subdivision_1_name":"New South Wales","$initial_geoip_subdivision_2_code":null,"$initial_geoip_subdivision_2_name":null,"current_organization_membership_level":15},"groups":{},"app_version":null,"platform":"Desktop","device_brand":"","carrier":"","country":"Australia","region":"","city":"Sydney","language":null,"utm_properties":{"utm_term":null,"utm_medium":null,"utm_source":null,"utm_content":null,"utm_campaign":null},"referrer":"http://localhost:8000/project/1/pipeline/new/destination/hog-template-meta-ads?showPaused=true&kind&search=meta","internal_partner_action":"logEventV2","debug_mode":true,"library":"segment"}]}",
                    "headers": {
                      "Content-Type": "application/json",
                    },
                    "method": "POST",
                  },
                ]
            `)

            expect(jest.mocked(processor['cyclotronJobQueue']!.queueInvocationResults).mock.calls[0][0]).toMatchObject([
                {
                    finished: true,
                },
            ])
        }, 10000)

        it('should handle fetch errors', async () => {
            jest.spyOn(amplitudeAction as any, 'perform')

            fn = await insertHogFunction({
                name: 'Plugin test',
                template_id: 'segment-amplitude',
            })

            const invocation = createExampleSegmentInvocation(fn, amplitudeInputs)

            mockFetch.mockResolvedValue({
                status: 403,
                json: () => Promise.resolve({ error: 'Forbidden' }),
                text: () => Promise.resolve(JSON.stringify({ error: 'Forbidden' })),
                headers: { 'retry-after': '60' },
            })

            const { invocationResults } = await processor.processBatch([invocation])

            expect(invocationResults.length).toBe(1)

            invocationResults[0].logs.forEach((x) => {
                if (typeof x.message === 'string' && x.message.includes('Function completed in')) {
                    x.message = 'Function completed in [REPLACED]'
                }
            })

            expect(invocationResults[0].logs).toMatchSnapshot()

            expect(amplitudeAction.perform).toHaveBeenCalledTimes(1)
            expect(forSnapshot(jest.mocked(amplitudeAction.perform!).mock.calls[0][1])).toMatchSnapshot()

            expect(mockFetch).toHaveBeenCalledTimes(1)
            expect(forSnapshot(mockFetch.mock.calls[0])).toMatchInlineSnapshot(`
                [
                  "https://api2.amplitude.com/2/httpapi",
                  {
                    "body": "{"api_key":"api-key","events":[{"os_name":"Mac OS X","os_version":"10.15.7","device_manufacturer":null,"device_model":null,"apiKey":"api-key","user_id":"user-id","secretKey":"secret-key","device_id":"device-id","endpoint":"north_america","user_properties":{"$os":"Mac OS X","_kx":null,"epik":null,"test":"abcdefge","$host":"localhost:8010","dclid":null,"email":"max@posthog.com","gclid":null,"qclid":null,"realm":"hosted-clickhouse","sccid":null,"fbclid":null,"gbraid":null,"gclsrc":null,"igshid":null,"irclid":null,"mc_cid":null,"ttclid":null,"twclid":null,"wbraid":null,"msclkid":null,"rdt_cid":"asdfsad","$browser":"Chrome","utm_term":null,"$pathname":"/project/1/activity/explore","$referrer":"http://localhost:8000/project/1/pipeline/new/destination/hog-template-meta-ads?showPaused=true&kind&search=meta","joined_at":"2025-04-04T11:33:18.022897+00:00","li_fat_id":null,"strapi_id":null,"gad_source":null,"project_id":"<REPLACED-UUID-0>","utm_medium":null,"utm_source":null,"$initial_os":"Mac OS X","$os_version":"10.15.7","utm_content":null,"$current_url":"http://localhost:8000/project/1/activity/explore","$device_type":"Desktop","$initial__kx":null,"instance_tag":"none","instance_url":"http://localhost:8010","is_signed_up":true,"utm_campaign":null,"$initial_epik":null,"$initial_host":"localhost:8010","$screen_width":2560,"project_count":1,"$initial_dclid":null,"$initial_gclid":null,"$initial_qclid":null,"$initial_sccid":null,"$screen_height":1440,"$search_engine":"google","anonymize_data":false,"$geoip_latitude":-33.8715,"$initial_fbclid":null,"$initial_gbraid":null,"$initial_gclsrc":null,"$initial_igshid":null,"$initial_irclid":null,"$initial_mc_cid":null,"$initial_ttclid":null,"$initial_twclid":null,"$initial_wbraid":null,"$raw_user_agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36","$viewport_width":1698,"has_social_auth":false,"organization_id":"<REPLACED-UUID-1>","$browser_version":135,"$geoip_city_name":"Sydney","$geoip_longitude":151.2006,"$geoip_time_zone":"Australia/Sydney","$initial_browser":"Chrome","$initial_msclkid":null,"$initial_rdt_cid":null,"$viewport_height":1328,"has_password_set":true,"social_providers":[],"$initial_pathname":"/organization/billing","$initial_referrer":"$direct","$initial_utm_term":null,"$referring_domain":"localhost:8000","is_email_verified":false,"$geoip_postal_code":"2000","$initial_li_fat_id":null,"organization_count":1,"$creator_event_uuid":"<REPLACED-UUID-2>","$geoip_country_code":"AU","$geoip_country_name":"Australia","$initial_gad_source":null,"$initial_os_version":"15.2","$initial_utm_medium":null,"$initial_utm_source":null,"$initial_current_url":"http://localhost:8010/organization/billing?cancel=true","$initial_device_type":"Desktop","$initial_utm_content":null,"$geoip_continent_code":"OC","$geoip_continent_name":"Oceania","$initial_screen_width":2560,"$initial_utm_campaign":null,"team_member_count_all":1,"$geoip_accuracy_radius":20,"$geoip_city_confidence":null,"$initial_screen_height":1440,"project_setup_complete":false,"$initial_geoip_latitude":-33.8715,"$initial_raw_user_agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36","$initial_viewport_width":1619,"$initial_browser_version":134,"$initial_geoip_city_name":"Sydney","$initial_geoip_longitude":151.2006,"$initial_geoip_time_zone":"Australia/Sydney","$initial_viewport_height":1328,"$geoip_subdivision_1_code":"NSW","$geoip_subdivision_1_name":"New South Wales","$geoip_subdivision_2_code":null,"$geoip_subdivision_2_name":null,"$initial_referring_domain":"$direct","completed_onboarding_once":false,"$initial_geoip_postal_code":"2000","has_seen_product_intro_for":{"surveys":true},"$initial_geoip_country_code":"AU","$initial_geoip_country_name":"Australia","$initial_geoip_continent_code":"OC","$initial_geoip_continent_name":"Oceania","$initial_geoip_accuracy_radius":20,"$initial_geoip_city_confidence":null,"$initial_geoip_subdivision_1_code":"NSW","$initial_geoip_subdivision_1_name":"New South Wales","$initial_geoip_subdivision_2_code":null,"$initial_geoip_subdivision_2_name":null,"current_organization_membership_level":15},"groups":{},"app_version":null,"platform":"Desktop","device_brand":"","carrier":"","country":"Australia","region":"","city":"Sydney","language":null,"utm_properties":{"utm_term":null,"utm_medium":null,"utm_source":null,"utm_content":null,"utm_campaign":null},"referrer":"http://localhost:8000/project/1/pipeline/new/destination/hog-template-meta-ads?showPaused=true&kind&search=meta","internal_partner_action":"logEventV2","debug_mode":true,"library":"segment"}]}",
                    "headers": {
                      "Content-Type": "application/json",
                    },
                    "method": "POST",
                  },
                ]
            `)

            expect(
                jest.mocked(processor['cyclotronJobQueue']!.queueInvocationResults).mock.calls[0][0][0].invocation
            ).toEqual({
                globals: expect.any(Object),
                hogFunction: expect.any(Object),
                id: expect.any(String),
                queue: 'segment',
                queueMetadata: undefined,
                queueParameters: undefined,
                queuePriority: 0,
                queueScheduledAt: undefined,
                queueSource: undefined,
                teamId: 2,
                timings: [],
            })

            expect(jest.mocked(processor['cyclotronJobQueue']!.queueInvocationResults).mock.calls[0][0]).toMatchObject([
                {
                    finished: true,
                },
            ])
        }, 10000)

        it('works with multiple fetches', async () => {
            jest.spyOn(pipedriveAction as any, 'perform')

            const pipedriveInputs = {
                domain: 'posthog-sandbox',
                match_field: 'email',
                apiToken: 'api-key',
                match_value: 'max@posthog.com',
                personField: 'id',
                name: 'Max',
                organizationField: 'id',
                email: 'max@posthog.com',
                dealField: 'id',
                phone: null,
                custom_fields: {},
                internal_partner_action: 'createUpdatePerson',
                debug_mode: true,
            }

            fn = await insertHogFunction({
                name: 'Plugin test',
                template_id: 'segment-pipedrive',
            })

            const invocation = createExampleSegmentInvocation(fn, pipedriveInputs)

            mockFetch.mockResolvedValue({
                status: 200,
                json: () => Promise.resolve({ total_count: 1 }),
                text: () => Promise.resolve(JSON.stringify(pipedriveResponse)),
                headers: {},
            })

            const { invocationResults } = await processor.processBatch([invocation])

            expect(invocationResults.length).toBe(1)

            invocationResults[0].logs.forEach((x) => {
                if (typeof x.message === 'string' && x.message.includes('Function completed in')) {
                    x.message = 'Function completed in [REPLACED]'
                }
            })

            expect(invocationResults[0].logs).toMatchSnapshot()

            expect(pipedriveAction.perform).toHaveBeenCalledTimes(1)
            expect(forSnapshot(jest.mocked(pipedriveAction.perform!).mock.calls[0][1])).toMatchSnapshot()

            expect(mockFetch).toHaveBeenCalledTimes(2)
            expect(forSnapshot(mockFetch.mock.calls[0])).toMatchInlineSnapshot(`
                [
                  "https://posthog-sandbox.pipedrive.com/api/v1/itemSearch/field?term=max%40posthog.com&field_key=email&exact_match=true&field_type=personField&return_item_ids=true&api_token=api-key",
                  {
                    "body": undefined,
                    "headers": {},
                    "method": "GET",
                  },
                ]
            `)
            expect(forSnapshot(mockFetch.mock.calls[1])).toMatchInlineSnapshot(`
                [
                  "https://posthog-sandbox.pipedrive.com/api/v1/persons?api_token=api-key",
                  {
                    "body": "{"name":"Max","email":"max@posthog.com","phone":null}",
                    "headers": {
                      "Content-Type": "application/json",
                    },
                    "method": "POST",
                  },
                ]
            `)

            expect(jest.mocked(processor['cyclotronJobQueue']!.queueInvocationResults).mock.calls[0][0]).toMatchObject([
                {
                    finished: true,
                },
            ])
        }, 10000)
    })
})
