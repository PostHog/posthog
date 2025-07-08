import { IconInfo, IconMagicWand, IconPlus, IconRefresh, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonInput, LemonSelect, LemonTextArea, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { testEventGeneratorLogic, TestEventScenario } from './testEventGeneratorLogic'

export const TestEventGenerator = (): JSX.Element => {
    // Only show in development environment for safety
    if (process.env.NODE_ENV !== 'development') {
        return <></>
    }

    // Generate and persist UUID for distinct_id
    const generateUUID = (): string => {
        if (typeof crypto !== 'undefined' && crypto.randomUUID) {
            return crypto.randomUUID()
        }
        // Fallback for older browsers
        return 'test_user_' + Math.random().toString(36).substr(2, 9)
    }

    const generatedUUID = useRef<string>(generateUUID())
    
    const resetUUID = (): void => {
        generatedUUID.current = generateUUID()
        setCustomDistinctId(generatedUUID.current)
    }

    const {
        testModeEnabled,
        generatingEvents,
        generatedEvents,
        testScenarios,
        customEventName,
        customDistinctId,
        customUtmCampaign,
        customUtmSource,
        customUtmMedium,
        customTimestamp,
        customProperties,
    } = useValues(testEventGeneratorLogic)

    const {
        setTestMode,
        generateTestEvent,
        runTestScenario,
        clearGeneratedEvents,
        setCustomEventName,
        setCustomDistinctId,
        setCustomUtmCampaign,
        setCustomUtmSource,
        setCustomUtmMedium,
        setCustomTimestamp,
        setCustomProperties,
    } = useActions(testEventGeneratorLogic)

    // Initialize with generated UUID if using default value
    useEffect(() => {
        if (customDistinctId === 'test_user_1') {
            setCustomDistinctId(generatedUUID.current)
        }
    }, [customDistinctId, setCustomDistinctId])

    // Format event details for tooltip
    const formatEventDetails = (scenario: TestEventScenario): string => {
        return scenario.events.map((event, index) => {
            const utmParams = event.properties ? 
                Object.entries(event.properties)
                    .filter(([key]) => key.startsWith('utm_'))
                    .map(([key, value]) => `${key}: "${value}"`)
                    .join(', ') : ''
            
            const otherParams = event.properties ? 
                Object.entries(event.properties)
                    .filter(([key]) => !key.startsWith('utm_'))
                    .map(([key, value]) => `${key}: ${typeof value === 'string' ? `"${value}"` : value}`)
                    .join(', ') : ''
            
            const timestamp = event.timestamp ? ` (${event.timestamp})` : ''
            
            const propertiesDisplay = []
            if (utmParams) propertiesDisplay.push(`UTM: ${utmParams}`)
            if (otherParams) propertiesDisplay.push(`Properties: ${otherParams}`)
            if (propertiesDisplay.length === 0) propertiesDisplay.push('No properties')
            
            return `${index + 1}. Event: "${event.event}"
   User: ${event.distinctId}${timestamp}
   ${propertiesDisplay.join('\n   ')}`
        }).join('\n\n')
    }

    if (!testModeEnabled) {
        return (
            <div className="p-4 border-b border-border bg-bg-light">
                <div className="flex items-center justify-between">
                    <div>
                        <h3 className="text-sm font-semibold text-default">Attribution Testing</h3>
                        <p className="text-xs text-muted">Generate test events to verify UTM attribution logic</p>
                    </div>
                    <LemonButton
                        type="primary"
                        icon={<IconMagicWand />}
                        onClick={() => setTestMode(true)}
                        size="small"
                    >
                        Enable Test Mode
                    </LemonButton>
                </div>
            </div>
        )
    }

    const generateCustomEvent = () => {
        const properties: Record<string, any> = {}
        
        // Add UTM properties
        if (customUtmCampaign) {
            properties.utm_campaign = customUtmCampaign
        }
        if (customUtmSource) {
            properties.utm_source = customUtmSource
        }
        if (customUtmMedium) {
            properties.utm_medium = customUtmMedium
        }

        // Parse and add custom properties from JSON
        try {
            const customPropsValue = (customProperties as any) || ''
            if (customPropsValue && customPropsValue.trim()) {
                const parsed = JSON.parse(customPropsValue)
                Object.assign(properties, parsed)
            }
        } catch (error) {
            console.error('JFBW: Invalid JSON in custom properties:', error)
            // Continue with just UTM properties if JSON is invalid
        }

        generateTestEvent(
            customEventName,
            customDistinctId || generatedUUID.current,
            Object.keys(properties).length > 0 ? properties : undefined,
            customTimestamp || undefined
        )
    }

    return (
        <div className="border-b border-border bg-bg-light">
            <LemonCollapse
                defaultActiveKey="test-mode"
                panels={[
                    {
                        key: 'test-mode',
                        header: (
                            <div className="flex items-center justify-between w-full">
                                <div className="flex items-center gap-2">
                                    <IconMagicWand className="text-primary" />
                                    <div>
                                        <h3 className="text-sm font-semibold text-default">Attribution Testing Mode</h3>
                                        <p className="text-xs text-muted">
                                            Generate test events to verify your UTM attribution scenarios
                                        </p>
                                    </div>
                                </div>
                                <LemonButton
                                    type="secondary"
                                    size="xsmall"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        setTestMode(false)
                                    }}
                                >
                                    Disable Test Mode
                                </LemonButton>
                            </div>
                        ),
                        content: (
                            <div className="space-y-6">
                                {/* Predefined Test Scenarios */}
                                <div>
                                    <h4 className="text-sm font-medium mb-3">Predefined Test Scenarios</h4>
                                    <div className="grid gap-3">
                                        {testScenarios.map((scenario: TestEventScenario) => (
                                            <div
                                                key={scenario.id}
                                                className="p-3 border border-border rounded-md bg-surface-primary"
                                            >
                                                <div className="flex items-start justify-between">
                                                    <div className="flex-1">
                                                        <div className="flex items-center gap-2">
                                                            <h5 className="font-medium text-sm">{scenario.name}</h5>
                                                            <Tooltip
                                                                title={
                                                                    <div className="whitespace-pre-line text-xs">
                                                                        <div className="font-medium mb-2">Events to be generated:</div>
                                                                        {formatEventDetails(scenario)}
                                                                    </div>
                                                                }
                                                                placement="top"
                                                            >
                                                                <IconInfo className="text-muted-alt hover:text-default cursor-help w-4 h-4" />
                                                            </Tooltip>
                                                        </div>
                                                        <p className="text-xs text-muted mt-1">{scenario.description}</p>
                                                        <div className="text-xs text-muted-alt mt-2">
                                                            {scenario.events.length} events •{' '}
                                                            {new Set(scenario.events.map(e => e.distinctId)).size} users
                                                        </div>
                                                    </div>
                                                    <LemonButton
                                                        type="primary"
                                                        size="xsmall"
                                                        onClick={() => runTestScenario(scenario)}
                                                        loading={generatingEvents}
                                                        icon={<IconPlus />}
                                                    >
                                                        Run Scenario
                                                    </LemonButton>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>

                                {/* Custom Event Generator */}
                                <div>
                                    <h4 className="text-sm font-medium mb-3">Custom Event Generator</h4>
                                    <div className="p-4 border border-border rounded-md bg-surface-primary">
                                        <div className="grid grid-cols-2 gap-4 mb-4">
                                            <div>
                                                <label className="block text-xs font-medium text-default mb-1">
                                                    Event Name
                                                </label>
                                                <LemonInput
                                                    value={customEventName}
                                                    onChange={setCustomEventName}
                                                    placeholder="e.g., purchase, sign_up"
                                                    size="small"
                                                />
                                            </div>
                                            <div>
                                                <label className="block text-xs font-medium text-default mb-1">
                                                    User ID (distinct_id) 
                                                    <span className="text-muted-alt ml-1">• Auto-generated UUID</span>
                                                </label>
                                                <div className="flex gap-2">
                                                    <LemonInput
                                                        value={customDistinctId || generatedUUID.current}
                                                        onChange={setCustomDistinctId}
                                                        placeholder="e.g., test_user_1"
                                                        size="small"
                                                        className="flex-1"
                                                    />
                                                    <LemonButton
                                                        type="secondary"
                                                        size="small"
                                                        icon={<IconRefresh />}
                                                        onClick={resetUUID}
                                                        tooltip="Generate a new UUID for testing different users"
                                                    />
                                                </div>
                                            </div>
                                        </div>

                                        <div className="grid grid-cols-3 gap-4 mb-4">
                                            <div>
                                                <label className="block text-xs font-medium text-default mb-1">
                                                    UTM Campaign
                                                </label>
                                                <LemonInput
                                                    value={customUtmCampaign}
                                                    onChange={setCustomUtmCampaign}
                                                    placeholder="Leave empty for no UTM"
                                                    size="small"
                                                />
                                            </div>
                                            <div>
                                                <label className="block text-xs font-medium text-default mb-1">
                                                    UTM Source
                                                </label>
                                                <LemonInput
                                                    value={customUtmSource}
                                                    onChange={setCustomUtmSource}
                                                    placeholder="Leave empty for no UTM"
                                                    size="small"
                                                />
                                            </div>
                                            <div>
                                                <label className="block text-xs font-medium text-default mb-1">
                                                    UTM Medium
                                                </label>
                                                <LemonInput
                                                    value={customUtmMedium}
                                                    onChange={setCustomUtmMedium}
                                                    placeholder="Leave empty for no UTM"
                                                    size="small"
                                                />
                                            </div>
                                        </div>

                                        <div className="mb-4">
                                            <label className="block text-xs font-medium text-default mb-1">
                                                Timestamp (optional)
                                            </label>
                                            <LemonInput
                                                value={customTimestamp}
                                                onChange={setCustomTimestamp}
                                                placeholder="Leave empty for current time (format: YYYY-MM-DDTHH:mm:ssZ)"
                                                size="small"
                                            />
                                        </div>

                                        <div className="mb-4">
                                            <label className="block text-xs font-medium text-default mb-1">
                                                Custom Properties (JSON)
                                                <span className="text-muted-alt ml-1">• For testing sum aggregation, revenue, etc.</span>
                                            </label>
                                            <LemonTextArea
                                                value={(customProperties as any) || '{\n  "revenue": 100\n}'}
                                                onChange={(setCustomProperties as any)}
                                                placeholder='{\n  "revenue": 100,\n  "amount": 250,\n  "category": "premium"\n}'
                                                rows={4}
                                                className="font-mono text-xs"
                                            />
                                            <div className="text-xs text-muted-alt mt-1">
                                                💡 Add any properties for testing. These will be merged with UTM parameters above.
                                            </div>
                                        </div>

                                        <LemonButton
                                            type="primary"
                                            onClick={generateCustomEvent}
                                            icon={<IconPlus />}
                                            size="small"
                                        >
                                            Generate Custom Event
                                        </LemonButton>
                                    </div>
                                </div>

                                {/* Generated Events Log */}
                                {generatedEvents.length > 0 && (
                                    <div>
                                        <div className="flex items-center justify-between mb-3">
                                            <div>
                                                <h4 className="text-sm font-medium">Generated Events ({generatedEvents.length})</h4>
                                                <p className="text-xs text-muted-alt">💾 Persisted in localStorage</p>
                                            </div>
                                            <LemonButton
                                                type="secondary"
                                                size="xsmall"
                                                onClick={clearGeneratedEvents}
                                                icon={<IconTrash />}
                                            >
                                                Clear Log
                                            </LemonButton>
                                        </div>
                                        <div className="max-h-48 overflow-y-auto border border-border rounded-md bg-surface-primary">
                                            {generatedEvents.map((event, index) => (
                                                <div
                                                    key={index}
                                                    className="p-2 border-b border-border last:border-b-0 text-xs font-mono"
                                                >
                                                    <div className="flex items-center justify-between">
                                                        <span className="font-semibold text-primary">{event.event}</span>
                                                        <span className="text-muted-alt">{event.timestamp}</span>
                                                    </div>
                                                    <div className="text-muted mt-1">
                                                        distinct_id: {event.distinct_id || 'current_user'}
                                                    </div>
                                                    {event.properties && Object.keys(event.properties).length > 0 && (
                                                        <div className="text-muted mt-1">
                                                            {JSON.stringify(event.properties, null, 2)}
                                                        </div>
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {/* Instructions */}
                                <div className="p-3 bg-primary-highlight border border-primary rounded-md">
                                    <h5 className="text-sm font-medium text-primary mb-2">How to Test Attribution</h5>
                                    <ul className="text-xs text-primary space-y-1">
                                        <li>• <strong>Event UTM Priority:</strong> Events with UTM data use their own UTMs</li>
                                        <li>• <strong>Person UTM Fallback:</strong> Events without UTMs use person's most recent UTM data</li>
                                        <li>• <strong>Organic Default:</strong> No UTM data anywhere defaults to "organic"</li>
                                        <li>• Check your browser console for "JFBW:" logs to see event details</li>
                                        <li>• Refresh the analytics table to see attribution results</li>
                                    </ul>
                                </div>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
} 