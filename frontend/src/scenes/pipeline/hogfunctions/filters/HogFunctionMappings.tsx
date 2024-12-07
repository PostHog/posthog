// Mappings concept

// List of mappings where you can enable / disable them and add or remove
// When adding, select from a dropdown of options (these would be the "mappings_schema")
// Mappings schemas will have some "default enabled" thing to show them automatically
// The mapping schema should define whats possible including if custom schemas are possible
// For custom ones we can then have more options to map properties

import { IconArrowRight, IconEllipsis, IconFilter, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { LemonField } from 'lib/lemon-ui/LemonField'

// MAPPINGS_SCHEMA = [
//     {
//         mapping,
//     },
// ]

// let triggers = [
//     {
//         id: 'uuid',
//         filters: '...filters',
//         masking: '...masking',
//         mapping: {
//             event: 'Purchase completed',
//             properties: {
//                 url: '$current_url',
//             },
//         },
//     },
// ]

// Mappings would replace filters as the source for event filtering. Filtering would happen in addition as a global thing
// Every function would have a mapping, even if the default is just "All events" -> "{event.event}"
// The mapping would contain filters and masking info so it functions as a multi-source control

export type HogFunctionMapping = {
    id: string
    filters?: any
    source_event: string
    target_event: string
}

export type HogFunctionMappingEditorProps = {
    id: string
}

export function HogFunctionMappingEditor() {}

export function HogFunctionMappings(): JSX.Element {
    const mappings: HogFunctionMapping[] = [
        {
            id: '$pageview-page',
            source_event: '$pageview',
            target_event: 'Page',
        },
        {
            id: '$user-converted',
            source_event: 'purchase',
            target_event: 'User converted',
        },
    ]

    return (
        <>
            <LemonField
                name="mappings"
                label="Event mappings"
                info="Map PostHog events to the format expected by the destination"
            >
                {({ value, onChange }) => (
                    <>
                        {mappings.map((x) => (
                            <LemonButton
                                key={x.id}
                                type="secondary"
                                fullWidth
                                sideAction={{
                                    icon: <IconEllipsis />,
                                    dropdown: {
                                        placement: 'bottom-end',
                                        overlay: (
                                            <>
                                                <LemonButton
                                                    fullWidth
                                                    onClick={() => {
                                                        alert('TODO')
                                                    }}
                                                >
                                                    Duplicate
                                                </LemonButton>

                                                <LemonButton
                                                    fullWidth
                                                    onClick={() => {
                                                        alert('TODO')
                                                    }}
                                                >
                                                    Disable
                                                </LemonButton>

                                                <LemonButton
                                                    fullWidth
                                                    onClick={() => {
                                                        alert('TODO')
                                                    }}
                                                    status="danger"
                                                >
                                                    Remove
                                                </LemonButton>
                                            </>
                                        ),
                                    },
                                }}
                            >
                                <div className="flex flex-1 space-between gap-2">
                                    <span className="flex-1">
                                        {x.source_event}
                                        {x.filters ? <IconFilter /> : null}
                                    </span>
                                    <span className="flex-0">
                                        <IconArrowRight />
                                    </span>
                                    <span className="flex-1 text-right">{x.target_event}</span>
                                </div>
                            </LemonButton>
                        ))}

                        <div>
                            <LemonButton type="secondary" icon={<IconPlus />} size="small">
                                Add mapping
                            </LemonButton>
                        </div>
                    </>
                )}
            </LemonField>
        </>
    )
}
