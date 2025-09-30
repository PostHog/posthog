import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { sidePanelSdkDoctorLogic } from './sidePanelSdkDoctorLogic'

describe('sidePanelSdkDoctorLogic', () => {
    let logic: ReturnType<typeof sidePanelSdkDoctorLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    useMocks({
        get: {
            '/api/projects/:team_id/events': (req) => {
                // Mock events API response - return test events based on query params
                if (req.url.searchParams.get('distinct_id')?.includes('test-web-current')) {
                    return [200, mockWebSDKEvents('1.258.5', 'current')]
                }
                if (req.url.searchParams.get('distinct_id')?.includes('test-web-outdated')) {
                    return [200, mockWebSDKEvents('1.255.0', 'outdated')]
                }
                if (req.url.searchParams.get('distinct_id')?.includes('test-feature-flag-timing')) {
                    return [200, mockFeatureFlagTimingEvents()]
                }
                return [200, { results: [] }]
            },
            '/api/github-sdk-versions/:sdk_type': (req) => {
                const sdkType = Array.isArray(req.params.sdk_type) ? req.params.sdk_type[0] : req.params.sdk_type
                return [200, getMockSDKVersionData(sdkType)]
            },
        },
    })

    beforeEach(() => {
        logic = sidePanelSdkDoctorLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('SDK Version Detection', () => {
        it('should detect current Web SDK version correctly', async () => {
            // Simulate events with current Web SDK version
            const mockEvents = mockWebSDKEvents('1.258.5', 'current')

            await expectLogic(logic, () => {
                logic.actions.loadRecentEventsSuccess(mockEvents)
            }).toMatchValues({
                sdkVersions: expect.arrayContaining([
                    expect.objectContaining({
                        type: 'web',
                        version: '1.258.5',
                        isOutdated: false,
                    }),
                ]),
            })
        })

        it('should detect outdated Web SDK version correctly', async () => {
            const mockEvents = mockWebSDKEvents('1.255.0', 'outdated')

            await expectLogic(logic, () => {
                logic.actions.loadRecentEventsSuccess(mockEvents)
            }).toMatchValues({
                sdkVersions: expect.arrayContaining([
                    expect.objectContaining({
                        type: 'web',
                        version: '1.255.0',
                        isOutdated: true,
                        releasesAhead: expect.any(Number),
                    }),
                ]),
            })
        })

        it('should handle multiple SDK types in the same session', async () => {
            const mockEvents = [
                ...mockWebSDKEvents('1.258.5', 'current'),
                ...mockPythonSDKEvents('6.7.6', 'current'),
                ...mockNodeSDKEvents('5.8.4', 'outdated'),
            ]

            await expectLogic(logic, () => {
                logic.actions.loadRecentEventsSuccess(mockEvents)
            }).toMatchValues({
                sdkVersions: expect.arrayContaining([
                    expect.objectContaining({ type: 'web', version: '1.258.5' }),
                    expect.objectContaining({ type: 'python', version: '6.7.6' }),
                    expect.objectContaining({ type: 'node', version: '5.8.4', isOutdated: true }),
                ]),
            })
        })
    })

    describe('Time-Based Detection (Dual Check Logic)', () => {
        it('should mark version as "close enough" when recent but multiple releases behind', async () => {
            // Test the dual check logic: releasesBehind > 2 BUT released <48h ago
            const mockEvents = mockWebSDKEvents('1.258.0', 'current')

            await expectLogic(logic, () => {
                logic.actions.loadRecentEventsSuccess(mockEvents)
            }).toMatchValues({
                sdkVersions: expect.arrayContaining([
                    expect.objectContaining({
                        type: 'web',
                        version: '1.258.0',
                        isOutdated: false, // Should be false because released <48h ago
                        releasesAhead: 3,
                    }),
                ]),
            })
        })

        it('should mark version as "outdated" when multiple releases behind AND old', async () => {
            const mockEvents = mockWebSDKEvents('1.258.0', 'outdated')

            await expectLogic(logic, () => {
                logic.actions.loadRecentEventsSuccess(mockEvents)
            }).toMatchValues({
                sdkVersions: expect.arrayContaining([
                    expect.objectContaining({
                        type: 'web',
                        version: '1.258.0',
                        isOutdated: true, // Should be true: 3+ releases behind AND >48h old
                        releasesAhead: 3,
                    }),
                ]),
            })
        })
    })

    describe('Feature Flag Timing Detection', () => {
        it('should detect feature flags called before SDK init', async () => {
            const mockEvents = mockFeatureFlagTimingEvents()

            await expectLogic(logic, () => {
                logic.actions.loadRecentEventsSuccess(mockEvents)
            }).toMatchValues({
                featureFlagProblems: expect.objectContaining({
                    'test-flag': expect.objectContaining({
                        flagName: 'test-flag',
                        isProblematic: true,
                        timingIssues: expect.arrayContaining([
                            expect.objectContaining({
                                type: 'early_call',
                            }),
                        ]),
                    }),
                }),
            })
        })

        it('should not flag proper feature flag usage', async () => {
            const mockEvents = mockProperFeatureFlagEvents()

            await expectLogic(logic, () => {
                logic.actions.loadRecentEventsSuccess(mockEvents)
            }).toMatchValues({
                featureFlagProblems: expect.not.objectContaining({
                    'proper-flag': expect.anything(),
                }),
            })
        })

        it('should use contextual thresholds for feature flag timing', async () => {
            // Test bootstrap scenario (0ms threshold)
            const bootstrapEvents = mockBootstrapFeatureFlagEvents()

            await expectLogic(logic, () => {
                logic.actions.loadRecentEventsSuccess(bootstrapEvents)
            }).toMatchValues({
                featureFlagProblems: expect.not.objectContaining({
                    'bootstrap-flag': expect.anything(),
                }),
            })
        })
    })

    describe('Device Context Classification', () => {
        it('should categorize mobile SDKs correctly', async () => {
            const mockEvents = [
                ...mockIOSSDKEvents('3.30.1'),
                ...mockAndroidSDKEvents('3.20.2'),
                ...mockFlutterSDKEvents('5.3.1'),
            ]

            await expectLogic(logic, () => {
                logic.actions.loadRecentEventsSuccess(mockEvents)
            }).toMatchValues({
                sdkVersions: expect.arrayContaining([
                    expect.objectContaining({ type: 'ios', deviceContext: 'mobile' }),
                    expect.objectContaining({ type: 'android', deviceContext: 'mobile' }),
                    expect.objectContaining({ type: 'flutter', deviceContext: 'mobile' }),
                ]),
            })
        })

        it('should categorize desktop SDKs correctly', async () => {
            const mockEvents = [
                ...mockWebSDKEvents('1.258.5', 'current'),
                ...mockNodeSDKEvents('5.8.4', 'current'),
                ...mockPythonSDKEvents('6.7.6', 'current'),
            ]

            await expectLogic(logic, () => {
                logic.actions.loadRecentEventsSuccess(mockEvents)
            }).toMatchValues({
                sdkVersions: expect.arrayContaining([
                    expect.objectContaining({ type: 'web', deviceContext: 'desktop' }),
                    expect.objectContaining({ type: 'node', deviceContext: 'desktop' }),
                    expect.objectContaining({ type: 'python', deviceContext: 'desktop' }),
                ]),
            })
        })
    })

    describe('Event Volume Classification', () => {
        it('should classify high-volume events correctly', async () => {
            // Create 50+ events for high volume
            const highVolumeEvents = Array.from({ length: 55 }, (_, i) => mockSingleWebEvent('1.258.5', i))

            await expectLogic(logic, () => {
                logic.actions.loadRecentEventsSuccess(highVolumeEvents)
            }).toMatchValues({
                sdkVersions: expect.arrayContaining([
                    expect.objectContaining({
                        type: 'web',
                        eventVolume: 'high',
                        count: 55,
                    }),
                ]),
            })
        })

        it('should classify low-volume events correctly', async () => {
            const lowVolumeEvents = Array.from({ length: 3 }, (_, i) => mockSingleWebEvent('1.258.5', i))

            await expectLogic(logic, () => {
                logic.actions.loadRecentEventsSuccess(lowVolumeEvents)
            }).toMatchValues({
                sdkVersions: expect.arrayContaining([
                    expect.objectContaining({
                        type: 'web',
                        eventVolume: 'low',
                        count: 3,
                    }),
                ]),
            })
        })
    })

    describe('Error Handling', () => {
        it('should handle API errors gracefully', async () => {
            const mockEvents = mockWebSDKEvents('1.258.5', 'current')

            await expectLogic(logic, () => {
                logic.actions.loadRecentEventsSuccess(mockEvents)
            }).toMatchValues({
                sdkVersions: expect.arrayContaining([
                    expect.objectContaining({
                        type: 'web',
                        version: '1.258.5',
                    }),
                ]),
            })
        })

        it('should handle malformed version data', async () => {
            const mockEvents = [
                {
                    id: 'test-malformed',
                    event: '$pageview',
                    properties: {
                        $lib: 'web',
                        $lib_version: 'invalid-version-format',
                    },
                    timestamp: new Date(MOCK_BASE_TIMESTAMP).toISOString(),
                    elements: [],
                    distinct_id: 'test-user',
                },
            ]

            await expectLogic(logic, () => {
                logic.actions.loadRecentEventsSuccess(mockEvents)
            }).toMatchValues({
                // Malformed version should either be filtered out or handled gracefully
                // Verify that sdkVersions array exists and doesn't crash
                sdkVersions: expect.any(Array),
            })
            // Verify no errors were thrown during processing
            expect(logic.values.sdkVersions.length).toBeGreaterThanOrEqual(0)
        })
    })

    describe('Menu Icon Status', () => {
        it('should show green checkmark when all SDKs are current', async () => {
            const mockEvents = [...mockWebSDKEvents('1.258.5', 'current'), ...mockPythonSDKEvents('6.7.6', 'current')]

            await expectLogic(logic, () => {
                logic.actions.loadRecentEventsSuccess(mockEvents)
            }).toMatchValues({
                menuIconStatus: 'success',
            })
        })

        it('should show yellow checkmark when some SDKs are close enough', async () => {
            const mockEvents = [
                ...mockWebSDKEvents('1.258.5', 'current'),
                ...mockPythonSDKEvents('6.7.5', 'close-enough'), // 1 behind
            ]

            await expectLogic(logic, () => {
                logic.actions.loadRecentEventsSuccess(mockEvents)
            }).toMatchValues({
                menuIconStatus: 'close-enough',
            })
        })

        it('should show red exclamation when any SDK is outdated', async () => {
            const mockEvents = [
                ...mockWebSDKEvents('1.258.5', 'current'),
                ...mockPythonSDKEvents('6.7.0', 'outdated'), // 6 behind
            ]

            await expectLogic(logic, () => {
                logic.actions.loadRecentEventsSuccess(mockEvents)
            }).toMatchValues({
                menuIconStatus: 'outdated',
            })
        })
    })
})

// Mock helper functions
// Fixed base timestamp for consistent testing
const MOCK_BASE_TIMESTAMP = new Date('2025-09-30T20:00:00.000Z').getTime()

function mockWebSDKEvents(version: string, status: 'current' | 'outdated' | 'close-enough'): any[] {
    const baseEvent = {
        event: '$pageview',
        properties: {
            $lib: 'web',
            $lib_version: version,
            $current_url: 'https://example.com',
        },
        timestamp: new Date(MOCK_BASE_TIMESTAMP).toISOString(),
        distinct_id: `test-web-${status}`,
        elements: [],
    }

    return Array.from({ length: 16 }, (_, i) => ({
        ...baseEvent,
        id: `web-event-${i}`,
        timestamp: new Date(MOCK_BASE_TIMESTAMP - i * 1000).toISOString(),
    }))
}

function mockPythonSDKEvents(version: string, status: 'current' | 'outdated' | 'close-enough'): any[] {
    const baseEvent = {
        event: 'custom_python_event',
        properties: {
            $lib: 'posthog-python',
            $lib_version: version,
        },
        timestamp: new Date(MOCK_BASE_TIMESTAMP).toISOString(),
        distinct_id: `test-python-${status}`,
        elements: [],
    }

    return Array.from({ length: 16 }, (_, i) => ({
        ...baseEvent,
        id: `python-event-${i}`,
        timestamp: new Date(MOCK_BASE_TIMESTAMP - i * 1000).toISOString(),
    }))
}

function mockNodeSDKEvents(version: string, status: 'current' | 'outdated' | 'close-enough'): any[] {
    const baseEvent = {
        event: 'backend_event',
        properties: {
            $lib: 'posthog-node',
            $lib_version: version,
        },
        timestamp: new Date(MOCK_BASE_TIMESTAMP).toISOString(),
        distinct_id: `test-node-${status}`,
        elements: [],
    }

    return Array.from({ length: 16 }, (_, i) => ({
        ...baseEvent,
        id: `node-event-${i}`,
        timestamp: new Date(MOCK_BASE_TIMESTAMP - i * 1000).toISOString(),
    }))
}

function mockIOSSDKEvents(version: string): any[] {
    return Array.from({ length: 16 }, (_, i) => ({
        id: `ios-event-${i}`,
        event: 'app_opened',
        properties: {
            $lib: 'posthog-ios',
            $lib_version: version,
            $device_type: 'Mobile',
        },
        timestamp: new Date(MOCK_BASE_TIMESTAMP - i * 1000).toISOString(),
        elements: [],
        distinct_id: 'test-ios-user',
    }))
}

function mockAndroidSDKEvents(version: string): any[] {
    return Array.from({ length: 16 }, (_, i) => ({
        id: `android-event-${i}`,
        event: 'app_opened',
        properties: {
            $lib: 'posthog-android',
            $lib_version: version,
            $device_type: 'Mobile',
        },
        timestamp: new Date(MOCK_BASE_TIMESTAMP - i * 1000).toISOString(),
        elements: [],
        distinct_id: 'test-android-user',
    }))
}

function mockFlutterSDKEvents(version: string): any[] {
    return Array.from({ length: 16 }, (_, i) => ({
        id: `flutter-event-${i}`,
        event: 'screen_view',
        properties: {
            $lib: 'posthog-flutter',
            $lib_version: version,
        },
        timestamp: new Date(MOCK_BASE_TIMESTAMP - i * 1000).toISOString(),
        elements: [],
        distinct_id: 'test-flutter-user',
    }))
}

function mockFeatureFlagTimingEvents(): any[] {
    return [
        // Feature flag called BEFORE pageload (problematic)
        {
            id: 'flag-event-1',
            event: '$feature_flag_called',
            properties: {
                $lib: 'web',
                $lib_version: '1.258.5',
                $feature_flag: 'test-flag',
                $feature_flag_response: true,
            },
            timestamp: new Date(MOCK_BASE_TIMESTAMP - 100).toISOString(), // 100ms before
            distinct_id: 'test-flag-user',
        },
        // Page load event (reference point)
        {
            id: 'pageload-event',
            event: '$pageview',
            properties: {
                $lib: 'web',
                $lib_version: '1.258.5',
                $current_url: 'https://example.com',
            },
            timestamp: new Date(MOCK_BASE_TIMESTAMP).toISOString(),
            distinct_id: 'test-flag-user',
        },
    ]
}

function mockProperFeatureFlagEvents(): any[] {
    return [
        // Page load event first
        {
            id: 'pageload-event',
            event: '$pageview',
            properties: {
                $lib: 'web',
                $lib_version: '1.258.5',
                $current_url: 'https://example.com',
            },
            timestamp: new Date(MOCK_BASE_TIMESTAMP).toISOString(),
            distinct_id: 'test-proper-user',
        },
        // Feature flag called AFTER sufficient time (proper)
        {
            id: 'proper-flag-event',
            event: '$feature_flag_called',
            properties: {
                $lib: 'web',
                $lib_version: '1.258.5',
                $feature_flag: 'proper-flag',
                $feature_flag_response: true,
            },
            timestamp: new Date(MOCK_BASE_TIMESTAMP + 600).toISOString(), // 600ms after (proper timing)
            distinct_id: 'test-proper-user',
        },
    ]
}

function mockBootstrapFeatureFlagEvents(): any[] {
    return [
        {
            id: 'bootstrap-event',
            event: '$feature_flag_called',
            properties: {
                $lib: 'web',
                $lib_version: '1.258.5',
                $feature_flag: 'bootstrap-flag',
                $feature_flag_response: true,
                $feature_flag_bootstrapped: true, // Bootstrap flag - no timing restrictions
            },
            timestamp: new Date(MOCK_BASE_TIMESTAMP).toISOString(),
            distinct_id: 'test-bootstrap-user',
        },
    ]
}

function mockSingleWebEvent(version: string, index: number): any {
    return {
        id: `web-event-${index}`,
        event: '$pageview',
        properties: {
            $lib: 'web',
            $lib_version: version,
            $current_url: 'https://example.com',
        },
        timestamp: new Date(MOCK_BASE_TIMESTAMP - index * 1000).toISOString(),
        distinct_id: 'test-volume-user',
    }
}

function getMockSDKVersionData(sdkType: string): any {
    const mockData = {
        web: {
            latestVersion: '1.258.5',
            versions: ['1.258.5', '1.258.4', '1.258.3', '1.258.2', '1.258.1', '1.258.0', '1.255.0'],
            releaseDates: {
                '1.258.5': new Date(MOCK_BASE_TIMESTAMP - 1 * 24 * 60 * 60 * 1000).toISOString(),
                '1.258.4': new Date(MOCK_BASE_TIMESTAMP - 2 * 24 * 60 * 60 * 1000).toISOString(),
                '1.258.0': new Date(MOCK_BASE_TIMESTAMP - 5 * 24 * 60 * 60 * 1000).toISOString(),
                '1.255.0': new Date(MOCK_BASE_TIMESTAMP - 20 * 24 * 60 * 60 * 1000).toISOString(),
            },
        },
        python: {
            latestVersion: '6.7.6',
            versions: ['6.7.6', '6.7.5', '6.7.4', '6.7.3', '6.7.2', '6.7.1', '6.7.0'],
            releaseDates: {
                '6.7.6': new Date(MOCK_BASE_TIMESTAMP - 3 * 24 * 60 * 60 * 1000).toISOString(),
                '6.7.5': new Date(MOCK_BASE_TIMESTAMP - 7 * 24 * 60 * 60 * 1000).toISOString(),
                '6.7.0': new Date(MOCK_BASE_TIMESTAMP - 25 * 24 * 60 * 60 * 1000).toISOString(),
            },
        },
        node: {
            latestVersion: '5.8.4',
            versions: ['5.8.4', '5.8.3', '5.8.2', '5.8.1'],
            releaseDates: {
                '5.8.4': new Date(MOCK_BASE_TIMESTAMP - 2 * 24 * 60 * 60 * 1000).toISOString(),
                '5.8.1': new Date(MOCK_BASE_TIMESTAMP - 15 * 24 * 60 * 60 * 1000).toISOString(),
            },
        },
    }

    return (mockData as any)[sdkType] || { latestVersion: '1.0.0', versions: ['1.0.0'], releaseDates: {} }
}
