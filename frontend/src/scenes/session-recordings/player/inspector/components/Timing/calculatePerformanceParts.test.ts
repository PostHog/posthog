import { mapRRWebNetworkRequest } from 'scenes/session-recordings/player/inspector/performance-event-utils'
import { InitiatorType } from '../../../../../../../../.yalc/posthog-js'
import { calculatePerformanceParts } from 'scenes/session-recordings/player/inspector/components/Timing/NetworkRequestTiming'

jest.mock('lib/colors', () => {
    return {
        getSeriesColor: jest.fn(() => '#000000'),
    }
})

describe('calculatePerformanceParts', () => {
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
        expect(calculatePerformanceParts(mappedToPerfEvent)).toEqual({
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
})
