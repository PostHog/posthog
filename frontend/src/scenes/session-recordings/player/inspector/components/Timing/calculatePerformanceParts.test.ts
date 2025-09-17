import { InitiatorType } from 'posthog-js'

import { mapRRWebNetworkRequest } from 'scenes/session-recordings/apm/performance-event-utils'
import { calculatePerformanceParts } from 'scenes/session-recordings/apm/waterfall/TimingBar'

import { PerformanceEvent } from '~/types'

jest.mock('lib/colors', () => {
    return {
        getSeriesColor: jest.fn(() => '#000000'),
    }
})

describe('calculatePerformanceParts', () => {
    it('can calculate TTFB', () => {
        const perfEvent: PerformanceEvent = {
            connect_end: 9525.599999964237,
            connect_start: 9525.599999964237,
            decoded_body_size: 18260,
            domain_lookup_end: 9525.599999964237,
            domain_lookup_start: 9525.599999964237,
            duration: 935.5,
            encoded_body_size: 18260,
            entry_type: 'resource',
            fetch_start: 9525.599999964237,
            initiator_type: 'fetch',
            name: 'http://localhost:8000/api/organizations/@current/plugins/repository/',
            next_hop_protocol: 'http/1.1',
            redirect_end: 0,
            redirect_start: 0,
            render_blocking_status: 'non-blocking',
            request_start: 9803.099999964237,
            response_end: 10461.099999964237,
            response_start: 10428.399999976158,
            response_status: 200,
            secure_connection_start: 0,
            start_time: 9525.599999964237,
            time_origin: '1699990397357',
            timestamp: 1699990406882,
            transfer_size: 18560,
            window_id: '018bcf51-b1f0-7fe0-ac05-10543621f4f2',
            worker_start: 0,
            uuid: '12345',
            distinct_id: '23456',
            session_id: 'abcde',
            pageview_id: 'fghij',
            current_url: 'http://localhost:8000/insights',
        }

        const performanceMeasures = calculatePerformanceParts(perfEvent)
        expect(performanceMeasures.serverTimings).toEqual([])
        expect(performanceMeasures.networkTimings).toEqual({
            'request queuing time': {
                color: '#000000',
                end: 9803.099999964237,
                start: 9525.599999964237,
            },

            'waiting for first byte': {
                color: '#000000',
                end: 10428.399999976158,
                start: 9803.099999964237,
            },
            'receiving response': {
                color: '#000000',
                end: 10461.099999964237,
                start: 10428.399999976158,
            },
        })
    })

    it('can handle gravatar timings', () => {
        const gravatarReqRes = {
            name: 'https://www.gravatar.com/avatar/2e7d95b60efbe947f71009a1af1ba8d0?s=96&d=404',
            entryType: 'resource',
            initiatorType: 'fetch' as InitiatorType,
            deliveryType: '',
            nextHopProtocol: '',
            renderBlockingStatus: 'non-blocking',
            workerStart: 0,
            redirectStart: 0,
            redirectEnd: 0,
            domainLookupStart: 0,
            domainLookupEnd: 0,
            connectStart: 0,
            secureConnectionStart: 0,
            connectEnd: 0,
            requestStart: 0,
            responseStart: 0,
            firstInterimResponseStart: 0,
            // only fetch start and response end
            // and transfer size is 0
            // loaded from disk cache
            startTime: 18229,
            fetchStart: 18228.5,
            responseEnd: 18267.5,
            endTime: 18268,
            duration: 39,
            transferSize: 0,
            encodedBodySize: 0,
            decodedBodySize: 0,
            responseStatus: 200,
            serverTiming: [],
            timeOrigin: 1700296048424,
            timestamp: 1700296066652,
            method: 'GET',
            status: 200,
            requestHeaders: {},
            requestBody: null,
            responseHeaders: {
                'cache-control': 'max-age=300',
                'content-length': '13127',
                'content-type': 'image/png',
                expires: 'Sat, 18 Nov 2023 08:32:46 GMT',
                'last-modified': 'Wed, 02 Feb 2022 09:11:05 GMT',
            },
            responseBody: '�PNGblah',
        }
        const mappedToPerfEvent = mapRRWebNetworkRequest(gravatarReqRes, 'windowId', 1700296066652)
        const performanceMeasures = calculatePerformanceParts(mappedToPerfEvent)
        expect(performanceMeasures.serverTimings).toEqual([])
        expect(performanceMeasures.networkTimings).toEqual({
            // 'app cache' not included - end would be before beginning
            // 'connection time' has 0 length
            // 'dns lookup' has 0 length
            // 'redirect has 0 length
            // 'tls time' has 0 length
            // TTFB has 0 length
            'receiving response': {
                color: '#000000',
                end: 18267.5,
                start: 18228.5,
            },
        })
    })

    it('can handle no TLS connection timing', () => {
        const tlsFreeReqRes = {
            name: 'http://localhost:8000/decide/?v=3&ip=1&_=1700319068450&ver=1.91.1',
            entryType: 'resource',
            startTime: 6648,
            duration: 93.40000003576279,
            initiatorType: 'xmlhttprequest' as InitiatorType,
            deliveryType: '',
            nextHopProtocol: 'http/1.1',
            renderBlockingStatus: 'non-blocking',
            workerStart: 0,
            redirectStart: 0,
            redirectEnd: 0,
            fetchStart: 6647.699999988079,
            domainLookupStart: 6648.800000011921,
            domainLookupEnd: 6648.800000011921,
            connectStart: 6648.800000011921,
            secureConnectionStart: 0,
            connectEnd: 6649.300000011921,
            requestStart: 6649.5,
            responseStart: 6740.800000011921,
            firstInterimResponseStart: 0,
            responseEnd: 6741.100000023842,
            transferSize: 2383,
            encodedBodySize: 2083,
            decodedBodySize: 2083,
            responseStatus: 200,
            serverTiming: [],
            endTime: 6741,
            timeOrigin: 1700319061802,
            timestamp: 1700319068449,
            isInitial: true,
        }
        const mappedToPerfEvent = mapRRWebNetworkRequest(tlsFreeReqRes, 'windowId', 1700319068449)
        const performanceMeasures = calculatePerformanceParts(mappedToPerfEvent)
        expect(performanceMeasures.serverTimings).toEqual([])
        expect(performanceMeasures.networkTimings).toEqual({
            'app cache': {
                color: '#000000',
                end: 6648.800000011921,
                start: 6647.699999988079,
            },
            'connection time': {
                color: '#000000',
                end: 6649.300000011921,
                start: 6648.800000011921,
            },
            'waiting for first byte': {
                color: '#000000',
                end: 6740.800000011921,
                start: 6649.5,
            },
            'receiving response': {
                color: '#000000',
                end: 6741.100000023842,
                start: 6740.800000011921,
            },
            'request queuing time': {
                color: '#000000',
                end: 6649.5,
                start: 6649.300000011921,
            },
        })
    })

    it('can map server timings', () => {
        const tlsFreeReqRes = {
            name: 'http://localhost:8000/decide/?v=3&ip=1&_=1700319068450&ver=1.91.1',
            entryType: 'resource',
            startTime: 6648,
            duration: 93.40000003576279,
            initiatorType: 'xmlhttprequest' as InitiatorType,
            deliveryType: '',
            nextHopProtocol: 'http/1.1',
            renderBlockingStatus: 'non-blocking',
            workerStart: 0,
            redirectStart: 0,
            redirectEnd: 0,
            fetchStart: 6647.699999988079,
            domainLookupStart: 6648.800000011921,
            domainLookupEnd: 6648.800000011921,
            connectStart: 6648.800000011921,
            secureConnectionStart: 0,
            connectEnd: 6649.300000011921,
            requestStart: 6649.5,
            responseStart: 6740.800000011921,
            firstInterimResponseStart: 0,
            responseEnd: 6741.100000023842,
            transferSize: 2383,
            encodedBodySize: 2083,
            decodedBodySize: 2083,
            responseStatus: 200,
            endTime: 6741,
            timeOrigin: 1700319061802,
            timestamp: 1700319068449,
            isInitial: true,
        }
        const mappedToPerfEvent = mapRRWebNetworkRequest(tlsFreeReqRes, 'windowId', 1700319068449)
        mappedToPerfEvent.server_timings = [
            { name: 'cache', start_time: 123, duration: 0.1 } as unknown as PerformanceEvent,
            { name: 'app', start_time: 123, duration: 0.2 } as unknown as PerformanceEvent,
            { name: 'db', start_time: 123, duration: 0.3 } as unknown as PerformanceEvent,
        ]
        const performanceMeasures = calculatePerformanceParts(mappedToPerfEvent)
        expect(performanceMeasures.serverTimings).toEqual([
            { color: '#000000', end: 6648.1, label: 'cache', start: 6648 },
            { color: '#000000', end: 6648.2, label: 'app', start: 6648 },
            { color: '#000000', end: 6648.3, label: 'db', start: 6648 },
        ])
        expect(performanceMeasures.networkTimings).toEqual({
            'app cache': {
                color: '#000000',
                end: 6648.800000011921,
                start: 6647.699999988079,
            },
            'connection time': {
                color: '#000000',
                end: 6649.300000011921,
                start: 6648.800000011921,
            },
            'waiting for first byte': {
                color: '#000000',
                end: 6740.800000011921,
                start: 6649.5,
            },
            'receiving response': {
                color: '#000000',
                end: 6741.100000023842,
                start: 6740.800000011921,
            },
            'request queuing time': {
                color: '#000000',
                end: 6649.5,
                start: 6649.300000011921,
            },
        })
    })
})
