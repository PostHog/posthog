// PROTOTYPE, throwaway: variants I and J's handoff, a workflow triggered by each match of a Replay Vision scanner.
import { router } from 'kea-router'

import { PropertyFilterType, PropertyOperator } from '~/types'

import {
    captureMessageAudienceClicked,
    messageAudienceUrl,
} from 'products/workflows/frontend/MessageAudience/messageAudience'

interface ScannerForWorkflow {
    id: string
    scanner_type?: string
}

export function openScannerWorkflow(scanner: ScannerForWorkflow, source: string): void {
    captureMessageAudienceClicked(source, 'workflow')
    const properties = [
        {
            key: 'scanner_id',
            value: [scanner.id],
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        },
        // A monitor emits a result for every scan, so only a "yes" verdict is a match worth an email.
        ...(scanner.scanner_type === 'monitor'
            ? [
                  {
                      key: 'scanner_output_verdict',
                      value: ['yes'],
                      operator: PropertyOperator.Exact,
                      type: PropertyFilterType.Event,
                  },
              ]
            : []),
    ]
    router.actions.push(
        messageAudienceUrl(
            {
                source,
                sourceRecord: `replay_scanner:${scanner.id}`,
                properties: [],
                workflowEmail: {
                    subject: 'Can we help?',
                    paragraphs: [
                        'Hi,',
                        "It looks like something got in your way. Reply to this email and we'll help you finish.",
                    ],
                },
                workflowTrigger: {
                    type: 'event',
                    filters: {
                        events: [
                            // pinned: event name emitted by Replay Vision for each scan result
                            {
                                id: '$recording_observed',
                                name: '$recording_observed',
                                type: 'events',
                                order: 0,
                                properties,
                            },
                        ],
                    },
                },
            },
            'workflow'
        )
    )
}
