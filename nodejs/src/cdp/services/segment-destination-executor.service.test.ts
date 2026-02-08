import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime, Settings } from 'luxon'

import { defaultConfig } from '~/config/config'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { parseJSON } from '~/utils/json-parse'

import { createHogFunction } from '../_tests/fixtures'
import {
    amplitudeInputs,
    createExampleSegmentInvocation,
    gameballInputs,
    pipedriveResponse,
} from '../_tests/fixtures-segment'
import { SEGMENT_DESTINATIONS_BY_ID } from '../segment/segment-templates'
import { SegmentDestinationExecutorService } from './segment-destination-executor.service'

describe('SegmentDestinationExecutorService', () => {
    let service: SegmentDestinationExecutorService

    const amplitudePlugin = SEGMENT_DESTINATIONS_BY_ID['segment-actions-amplitude']
    const amplitudeAction = amplitudePlugin.destination.actions['logEventV2']

    const gameballPlugin = SEGMENT_DESTINATIONS_BY_ID['segment-actions-gameball']
    const gameballAction = gameballPlugin.destination.actions['trackEvent']

    const pipedrivePlugin = SEGMENT_DESTINATIONS_BY_ID['segment-actions-pipedrive']
    const pipedriveAction = pipedrivePlugin.destination.actions['createUpdatePerson']
    const pipedriveActivitiesAction = pipedrivePlugin.destination.actions['createUpdateActivity']

    beforeEach(() => {
        mockFetch.mockReset()

        Settings.defaultZone = 'UTC'
        service = new SegmentDestinationExecutorService(defaultConfig)

        mockFetch.mockImplementation((_url, _options) =>
            Promise.resolve({
                status: 200,
                json: () => Promise.resolve({}),
                text: () => Promise.resolve(JSON.stringify({})),
                headers: {},
                dump: () => Promise.resolve(),
            } as any)
        )

        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
        jest.spyOn(amplitudeAction as any, 'perform')
        jest.spyOn(pipedriveAction as any, 'perform')
        jest.spyOn(pipedriveActivitiesAction as any, 'perform')
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('segment plugins', () => {
        it('should call the plugin perform method', async () => {
            const fn = createHogFunction({
                name: 'Plugin test',
                template_id: 'segment-actions-amplitude',
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
                dump: () => Promise.resolve(),
            })

            const result = await service.execute(invocation)

            expect(result.finished).toBe(true)

            result.logs.forEach((x) => {
                if (typeof x.message === 'string' && x.message.includes('Function completed in')) {
                    x.message = 'Function completed in [REPLACED]'
                }
            })

            expect(result.logs).toMatchSnapshot()

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
        })

        it('should handle non retryable fetch errors', async () => {
            jest.spyOn(amplitudeAction as any, 'perform')

            const fn = createHogFunction({
                name: 'Plugin test',
                template_id: 'segment-actions-amplitude',
            })

            const invocation = createExampleSegmentInvocation(fn, amplitudeInputs)

            mockFetch.mockResolvedValue({
                status: 403,
                json: () => Promise.resolve({ error: 'Forbidden' }),
                text: () => Promise.resolve(JSON.stringify({ error: 'Forbidden' })),
                headers: { 'retry-after': '60' },
                dump: () => Promise.resolve(),
            })

            const result = await service.execute(invocation)

            expect(result.finished).toBe(true)

            result.logs.forEach((x) => {
                if (typeof x.message === 'string' && x.message.includes('Function completed in')) {
                    x.message = 'Function completed in [REPLACED]'
                }
            })

            expect(result.logs).toMatchSnapshot()

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

            expect(result.invocation).toEqual({
                functionId: expect.any(String),
                hogFunction: expect.any(Object),
                id: expect.any(String),
                queue: 'hog',
                queueMetadata: {
                    tries: 1,
                },
                queuePriority: 0,
                queueParameters: undefined,
                queueScheduledAt: undefined,
                queueSource: undefined,
                state: expect.any(Object),
                teamId: 1,
            })
        })

        it('should retry retryable fetch errors', async () => {
            jest.spyOn(amplitudeAction as any, 'perform')

            const fn = createHogFunction({
                name: 'Plugin test',
                template_id: 'segment-actions-amplitude',
            })

            const invocation = createExampleSegmentInvocation(fn, amplitudeInputs)

            mockFetch.mockResolvedValue({
                status: 429,
                json: () => Promise.resolve({ error: 'Too many requests' }),
                text: () => Promise.resolve(JSON.stringify({ error: 'Too many requests' })),
                headers: { 'retry-after': '60' },
                dump: () => Promise.resolve(),
            })

            const result = await service.execute(invocation)

            expect(result.finished).toBe(false)

            result.logs.forEach((x) => {
                if (typeof x.message === 'string' && x.message.includes('Function completed in')) {
                    x.message = 'Function completed in [REPLACED]'
                }
            })

            expect(result.logs).toMatchSnapshot()

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

            expect(result.invocation).toEqual({
                hogFunction: expect.any(Object),
                functionId: expect.any(String),
                id: expect.any(String),
                queue: 'hog',
                queueMetadata: { tries: 1 },
                queueParameters: undefined,
                queuePriority: 1,
                queueScheduledAt: expect.any(Object),
                queueSource: undefined,
                state: expect.any(Object),
                teamId: 1,
            })

            let minBackoffMs = DateTime.utc().plus({ milliseconds: defaultConfig.CDP_FETCH_BACKOFF_BASE_MS }).toMillis()
            let maxBackoffMs = DateTime.utc()
                .plus({ milliseconds: defaultConfig.CDP_FETCH_BACKOFF_BASE_MS * 2 })
                .toMillis()
            let scheduledAt = result.invocation.queueScheduledAt!.toMillis()
            expect(scheduledAt > minBackoffMs && scheduledAt < maxBackoffMs).toBe(true)

            // second fetch call

            const invocationResults2 = await service.execute(result.invocation)

            expect(invocationResults2.finished).toBe(false)

            expect(amplitudeAction.perform).toHaveBeenCalledTimes(2)

            expect(invocationResults2.invocation).toEqual({
                hogFunction: expect.any(Object),
                functionId: expect.any(String),
                id: expect.any(String),
                queue: 'hog',
                queueMetadata: {
                    tries: 2,
                },
                queueParameters: undefined,
                queuePriority: 2,
                queueScheduledAt: expect.any(Object),
                queueSource: undefined,
                state: expect.any(Object),
                teamId: 1,
            })

            minBackoffMs = DateTime.utc()
                .plus({ milliseconds: defaultConfig.CDP_FETCH_BACKOFF_BASE_MS * 2 })
                .toMillis()
            maxBackoffMs = DateTime.utc()
                .plus({ milliseconds: defaultConfig.CDP_FETCH_BACKOFF_BASE_MS * 3 })
                .toMillis()
            scheduledAt = invocationResults2.invocation.queueScheduledAt!.toMillis()
            expect(scheduledAt > minBackoffMs && scheduledAt < maxBackoffMs).toBe(true)

            // third fetch call

            const invocationResults3 = await service.execute(invocationResults2.invocation)

            expect(invocationResults3.finished).toBe(true)

            expect(amplitudeAction.perform).toHaveBeenCalledTimes(3)

            expect(invocationResults3.invocation).toEqual({
                hogFunction: expect.any(Object),
                functionId: expect.any(String),
                id: expect.any(String),
                queue: 'hog',
                queueMetadata: { tries: 3 },
                queueParameters: undefined,
                queuePriority: 0,
                queueScheduledAt: undefined,
                queueSource: undefined,
                state: expect.any(Object),
                teamId: 1,
            })
        })

        it('should handle throwHttpErrors flag', async () => {
            // This destination is setting the throwHttpErrors flag to false, so we should return the error to the function instead.
            // https://github.com/segmentio/action-destinations/blob/main/packages/destination-actions/src/destinations/gameball/util.ts#L68
            jest.spyOn(gameballAction as any, 'perform')

            const fn = createHogFunction({
                name: 'Plugin test',
                template_id: 'segment-actions-gameball',
            })

            const invocation = createExampleSegmentInvocation(fn, gameballInputs)

            mockFetch.mockResolvedValue({
                status: 403,
                json: () => Promise.resolve({ error: 'Forbidden' }),
                text: () => Promise.resolve(JSON.stringify({ error: 'Forbidden' })),
                headers: { 'retry-after': '60' },
                dump: () => Promise.resolve(),
            })

            const result = await service.execute(invocation)

            expect(result.finished).toBe(true)

            result.logs.forEach((x) => {
                if (typeof x.message === 'string' && x.message.includes('Function completed in')) {
                    x.message = 'Function completed in [REPLACED]'
                }
            })

            expect(result.logs).toMatchSnapshot()

            expect(gameballAction.perform).toHaveBeenCalledTimes(1)
            expect(forSnapshot(jest.mocked(gameballAction.perform!).mock.calls[0][1])).toMatchSnapshot()

            expect(mockFetch).toHaveBeenCalledTimes(1)
            expect(forSnapshot(mockFetch.mock.calls[0])).toMatchInlineSnapshot(`
                [
                  "https://api.gameball.co/api/v3.0/integrations/event",
                  {
                    "body": "{"events":{"$web_vitals":{"$geoip_city_name":"Aylesbury","$geoip_country_name":"United Kingdom","$geoip_country_code":"GB","$geoip_continent_name":"Europe","$geoip_continent_code":"EU","$geoip_postal_code":"HP21","$geoip_latitude":51.8053,"$geoip_longitude":-0.8086,"$geoip_accuracy_radius":500,"$geoip_time_zone":"Europe/London","$geoip_subdivision_1_code":"ENG","$geoip_subdivision_1_name":"England","$geoip_subdivision_2_code":"BKM","$geoip_subdivision_2_name":"Buckinghamshire"}},"playerUniqueId":"<REPLACED-UUID-0>"}",
                    "headers": {
                      "APIKey": "abc",
                      "Content-Type": "application/json",
                      "x-gb-agent": "GB/Segment",
                    },
                    "method": "POST",
                  },
                ]
            `)

            expect(result.invocation).toEqual({
                hogFunction: expect.any(Object),
                functionId: expect.any(String),
                id: expect.any(String),
                queue: 'hog',
                queueMetadata: { tries: 1 },
                queueParameters: undefined,
                queuePriority: 0,
                queueScheduledAt: undefined,
                queueSource: undefined,
                state: expect.any(Object),
                teamId: 1,
            })
        })

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

            const fn = createHogFunction({
                name: 'Plugin test',
                template_id: 'segment-actions-pipedrive',
            })

            const invocation = createExampleSegmentInvocation(fn, pipedriveInputs)

            mockFetch.mockResolvedValue({
                status: 200,
                json: () => Promise.resolve({ total_count: 1 }),
                text: () => Promise.resolve(JSON.stringify(pipedriveResponse)),
                headers: {},
                dump: () => Promise.resolve(),
            })

            const result = await service.execute(invocation)

            expect(result.finished).toBe(true)

            result.logs.forEach((x) => {
                if (typeof x.message === 'string' && x.message.includes('Function completed in')) {
                    x.message = 'Function completed in [REPLACED]'
                }
            })

            expect(result.logs).toMatchSnapshot()

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

            expect(result.finished).toBe(true)
        })

        it('handles activity_id field correctly for pipedrive activities action', async () => {
            jest.spyOn(pipedriveActivitiesAction as any, 'perform')

            const testCases = [
                { activity_id: null, shouldHaveId: false },
                { activity_id: '', shouldHaveId: false },
                { activity_id: '15', shouldHaveId: true },
            ]

            for (const testCase of testCases) {
                mockFetch.mockReset()

                const pipedriveInputs = {
                    domain: 'posthog-sandbox',
                    apiToken: 'api-key',
                    person_match_value: 'e252ca85-9ea2-4d17-9d99-5fda5535995d',
                    activity_id: testCase.activity_id,
                    personField: 'id',
                    organization_match_value: '',
                    organizationField: 'id',
                    deal_match_value: null,
                    dealField: 'id',
                    subject: null,
                    type: null,
                    description: null,
                    note: null,
                    due_date: null,
                    due_time: null,
                    duration: null,
                    done: null,
                    internal_partner_action: 'createUpdateActivity',
                    debug_mode: true,
                }

                const fn = createHogFunction({
                    name: 'Plugin test',
                    template_id: 'segment-actions-pipedrive',
                })

                const invocation = createExampleSegmentInvocation(fn, pipedriveInputs)

                mockFetch.mockResolvedValue({
                    status: 200,
                    json: () => Promise.resolve({ total_count: 1 }),
                    text: () => Promise.resolve(JSON.stringify(pipedriveResponse)),
                    headers: {},
                    dump: () => Promise.resolve(),
                })

                await service.execute(invocation)

                expect(mockFetch).toHaveBeenCalledTimes(2)

                const requestBody = parseJSON(mockFetch.mock.calls[1][1].body)
                const endpoint = mockFetch.mock.calls[1][0]

                if (testCase.shouldHaveId) {
                    expect(endpoint).toBe(
                        `https://posthog-sandbox.pipedrive.com/api/v1/activities/${testCase.activity_id}?api_token=api-key`
                    )
                } else {
                    expect(requestBody).not.toHaveProperty('id')
                    expect(endpoint).toBe('https://posthog-sandbox.pipedrive.com/api/v1/activities?api_token=api-key')
                }
            }
        })
    })
})
