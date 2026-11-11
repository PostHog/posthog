import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonCheckbox, LemonCollapse, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { PlatformAlertDestinationEventKindEnumApi } from '../generated/api.schemas'
import { ALL_ROUTE_EVENT_KINDS, ROUTE_EVENT_KIND_OPTIONS, receiverTarget } from './platformAlertRoutingFormat'
import { platformAlertRoutingLogic } from './platformAlertRoutingLogic'
import { RouteMatchersField } from './RouteMatchersField'

export function PlatformAlertRouteModal(): JSX.Element {
    const { routeModalOpen, editingRoute, routeForm, isRouteFormSubmitting, receivers } =
        useValues(platformAlertRoutingLogic)
    const { closeRouteModal, submitRouteForm } = useActions(platformAlertRoutingLogic)
    const customEvents = routeForm.eventKinds.length !== ALL_ROUTE_EVENT_KINDS.length

    return (
        <LemonModal
            isOpen={routeModalOpen}
            onClose={closeRouteModal}
            title={editingRoute ? 'Edit route' : 'New route'}
            description="Alerts whose labels match every condition also send to the route's receiver, alongside their own destinations."
            width={560}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeRouteModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitRouteForm}
                        loading={isRouteFormSubmitting}
                        data-attr="platform-alert-route-save"
                    >
                        {editingRoute ? 'Save' : 'Add route'}
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={platformAlertRoutingLogic}
                formKey="routeForm"
                enableFormOnSubmit
                className="flex flex-col gap-4"
            >
                <LemonField name="receiverId" label="Send to">
                    <LemonSelect
                        fullWidth
                        placeholder="Choose a receiver"
                        options={(receivers ?? []).map((receiver) => ({
                            value: receiver.id,
                            label: receiver.name,
                            labelInMenu: (
                                <div className="flex flex-col">
                                    <span>{receiver.name}</span>
                                    <span className="text-xs text-secondary">{receiverTarget(receiver)}</span>
                                </div>
                            ),
                        }))}
                        data-attr="platform-alert-route-receiver"
                    />
                </LemonField>
                <LemonField name="matchers" label="When the alert's labels match">
                    <RouteMatchersField />
                </LemonField>
                <LemonCollapse
                    panels={[
                        {
                            key: 'advanced',
                            header: customEvents
                                ? `Advanced options (${routeForm.eventKinds.length} of ${ALL_ROUTE_EVENT_KINDS.length} events)`
                                : 'Advanced options',
                            content: (
                                <LemonField
                                    name="eventKinds"
                                    label="Events to send"
                                    help="The alert changes the receiver hears about through this route."
                                >
                                    {({ value, onChange }) => (
                                        <div className="flex flex-wrap gap-4">
                                            {ROUTE_EVENT_KIND_OPTIONS.map((option) => (
                                                <LemonCheckbox
                                                    key={option.value}
                                                    label={option.label}
                                                    checked={(
                                                        value as PlatformAlertDestinationEventKindEnumApi[]
                                                    ).includes(option.value)}
                                                    onChange={(checked) =>
                                                        onChange(
                                                            checked
                                                                ? ALL_ROUTE_EVENT_KINDS.filter(
                                                                      (kind) =>
                                                                          kind === option.value || value.includes(kind)
                                                                  )
                                                                : value.filter(
                                                                      (
                                                                          kind: PlatformAlertDestinationEventKindEnumApi
                                                                      ) => kind !== option.value
                                                                  )
                                                        )
                                                    }
                                                    data-attr={`platform-alert-route-event-${option.value}`}
                                                />
                                            ))}
                                        </div>
                                    )}
                                </LemonField>
                            ),
                        },
                    ]}
                />
            </Form>
        </LemonModal>
    )
}
