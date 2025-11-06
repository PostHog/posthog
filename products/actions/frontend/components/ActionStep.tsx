import { useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, Link } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { OperandTag } from 'lib/components/PropertyFilters/components/OperandTag'
import { DEFAULT_TAXONOMIC_GROUP_TYPES } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { IconOpenInApp } from 'lib/lemon-ui/icons'

import { groupsModel } from '~/models/groupsModel'
import { ActionStepStringMatching, ActionStepType } from '~/types'

import { URL_MATCHING_HINTS } from '../utils/hints'
import { EventName } from './EventName'

const learnMoreLink = 'https://posthog.com/docs/data/actions?utm_medium=in-product&utm_campaign=action-page'

interface Props {
    step: ActionStepType
    actionId: number
    isOnlyStep: boolean
    index: number
    identifier: string
    disabledReason?: string
    onDelete: () => void
    onChange: (step: ActionStepType) => void
}

export function ActionStep({
    step,
    actionId,
    isOnlyStep,
    index,
    identifier,
    disabledReason,
    onDelete,
    onChange,
}: Props): JSX.Element {
    const sendStep = (stepToSend: ActionStepType): void => {
        onChange(stepToSend)
    }
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    return (
        <div className="bg-surface-primary rounded border p-3 relative">
            {index > 0 && !(index % 2 === 0) && (
                <div className="absolute top-1/2 -left-5">
                    <OperandTag operand="or" />
                </div>
            )}
            <div className="deprecated-space-y-4">
                <div className="flex items-center justify-between">
                    <b>Match Group #{index + 1}</b>

                    {!isOnlyStep && (
                        <LemonButton
                            className="absolute top-2 right-2"
                            icon={<IconX />}
                            size="small"
                            aria-label="delete"
                            onClick={onDelete}
                            disabledReason={disabledReason}
                        />
                    )}
                </div>
                <TypeSwitcher step={step} sendStep={sendStep} disabledReason={disabledReason} />

                {step.event === '$autocapture' && (
                    <AutocaptureFields
                        step={step}
                        sendStep={sendStep}
                        actionId={actionId}
                        disabledReason={disabledReason}
                    />
                )}
                {step.event !== undefined && step.event !== '$autocapture' && step.event !== '$pageview' && (
                    <div className="deprecated-space-y-1">
                        <LemonLabel>Event name</LemonLabel>
                        <EventName
                            value={step.event}
                            onChange={(value) =>
                                sendStep({
                                    ...step,
                                    event: value,
                                })
                            }
                            placeholder="All events"
                            allEventsOption="explicit"
                            disabled={!!disabledReason}
                        />

                        <small>
                            <Link to="https://posthog.com/docs/libraries" target="_blank">
                                See documentation
                            </Link>{' '}
                            on how to send custom events in lots of languages.
                        </small>
                    </div>
                )}
                {step.event === '$pageview' && (
                    <div>
                        <Option
                            step={step}
                            sendStep={sendStep}
                            item="url"
                            labelExtra={
                                <StringMatchingSelection
                                    field="url"
                                    step={step}
                                    sendStep={sendStep}
                                    disabledReason={disabledReason}
                                />
                            }
                            label="URL"
                            disabledReason={disabledReason}
                        />
                        {step.url_matching && step.url_matching in URL_MATCHING_HINTS && (
                            <small>{URL_MATCHING_HINTS[step.url_matching]}</small>
                        )}
                    </div>
                )}

                <div className="mt-4 deprecated-space-y-2">
                    <LemonLabel>Filters</LemonLabel>
                    <PropertyFilters
                        propertyFilters={step.properties}
                        pageKey={identifier}
                        eventNames={step.event ? [step.event] : []}
                        taxonomicGroupTypes={[...DEFAULT_TAXONOMIC_GROUP_TYPES, ...groupsTaxonomicTypes]}
                        onChange={(properties) => {
                            sendStep({
                                ...step,
                                properties: properties as [],
                            })
                        }}
                        showConditionBadge
                        disabledReason={disabledReason ?? undefined}
                    />
                </div>
            </div>
        </div>
    )
}

function Option({
    step,
    sendStep,
    item,
    label,
    placeholder = 'Specify a value to match on this',
    caption,
    labelExtra: extra_options,
    disabledReason,
}: {
    step: ActionStepType
    sendStep: (stepToSend: ActionStepType) => void
    item: keyof Pick<ActionStepType, 'href' | 'text' | 'selector' | 'url' | 'tag_name'>
    label: JSX.Element | string
    labelExtra?: JSX.Element | string
    placeholder?: string
    caption?: JSX.Element | string
    disabledReason?: string
}): JSX.Element {
    const onOptionChange = (val: string): void => {
        sendStep({
            ...step,
            [item]: val || null, // "" is a valid filter, we don't want it
        })
    }

    return (
        <div className="deprecated-space-y-1">
            <div className="flex flex-wrap gap-1">
                <LemonLabel>{label}</LemonLabel>
                {extra_options}
            </div>
            {caption && <div className="action-step-caption">{caption}</div>}
            <LemonInput
                data-attr="edit-action-url-input"
                allowClear
                onChange={onOptionChange}
                value={step[item] || ''}
                placeholder={placeholder}
                disabledReason={disabledReason}
            />
        </div>
    )
}

const AndSeparator = (): JSX.Element => {
    return (
        <div className="flex w-full justify-center">
            <OperandTag operand="and" />
        </div>
    )
}

function AutocaptureFields({
    step,
    actionId,
    sendStep,
    disabledReason,
}: {
    step: ActionStepType
    sendStep: (stepToSend: ActionStepType) => void
    actionId: number
    disabledReason?: string
}): JSX.Element {
    const onSelectElement = (): void => {
        LemonDialog.open({
            title: 'Select an element',
            description: actionId
                ? 'Choose the domain on which to edit this action'
                : 'Choose the domain on which to create this action',
            content: (
                <>
                    <AuthorizedUrlList actionId={actionId} type={AuthorizedUrlListType.TOOLBAR_URLS} />
                </>
            ),
            primaryButton: {
                children: 'Close',
                type: 'secondary',
            },
        })
    }
    return (
        <div className="deprecated-space-y-4">
            <div className="flex items-center gap-2">
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={onSelectElement}
                    sideIcon={<IconOpenInApp />}
                    disabledReason={disabledReason}
                >
                    Select element on site
                </LemonButton>
                <Link to={`${learnMoreLink}#1-autocapture`} target="_blank">
                    See documentation.
                </Link>
            </div>
            <Option
                step={step}
                sendStep={sendStep}
                item="text"
                labelExtra={
                    <StringMatchingSelection
                        field="text"
                        step={step}
                        sendStep={sendStep}
                        disabledReason={disabledReason}
                    />
                }
                label="Element text"
                disabledReason={disabledReason}
            />
            <AndSeparator />
            <Option
                step={step}
                sendStep={sendStep}
                item="href"
                labelExtra={
                    <StringMatchingSelection
                        field="href"
                        step={step}
                        sendStep={sendStep}
                        disabledReason={disabledReason}
                    />
                }
                label="Element link target"
                caption={
                    <>
                        Filtering by the <code>href</code> attribute. Only <code>{'<a/>'}</code> elements will be
                        matched.
                    </>
                }
                disabledReason={disabledReason}
            />
            {step['tag_name'] ? (
                <>
                    <AndSeparator />
                    <Option
                        step={step}
                        sendStep={sendStep}
                        item="tag_name"
                        label="Element matches tag name"
                        caption={
                            <span>
                                Filtering by the tag name of the element. This field is deprecated and superseded by the
                                HTML selector below. We recommend adding the tag name to the HTML selector field
                                instead. This field will disappear when cleared.
                            </span>
                        }
                        disabledReason={disabledReason}
                    />
                </>
            ) : undefined}
            <AndSeparator />
            <Option
                step={step}
                sendStep={sendStep}
                item="selector"
                label="Element matches HTML selector"
                caption={
                    <span>
                        The selector can be a tag name, class, HTML attribute, or all of those combined. Example:{' '}
                        <code>button[data-attr="signup"]</code>.{' '}
                        <Link to={`${learnMoreLink}#matching-selectors`}>Learn more in Docs.</Link>
                    </span>
                }
                disabledReason={disabledReason}
            />
            <AndSeparator />
            <Option
                step={step}
                sendStep={sendStep}
                item="url"
                labelExtra={
                    <StringMatchingSelection
                        field="url"
                        step={step}
                        sendStep={sendStep}
                        disabledReason={disabledReason}
                    />
                }
                label="Page URL"
                caption="The page on which the interaction occurred."
                disabledReason={disabledReason}
            />
            {step?.url_matching && step.url_matching in URL_MATCHING_HINTS && (
                <small>{URL_MATCHING_HINTS[step.url_matching]}</small>
            )}
        </div>
    )
}

function TypeSwitcher({
    step,
    sendStep,
    disabledReason,
}: {
    step: ActionStepType
    sendStep: (stepToSend: ActionStepType) => void
    disabledReason?: string
}): JSX.Element {
    const handleChange = (type: string): void => {
        if (type === '$autocapture') {
            sendStep({ ...step, event: '$autocapture' })
        } else if (type === 'event') {
            sendStep({ ...step, event: null })
        } else if (type === '$pageview') {
            sendStep({
                ...step,
                event: '$pageview',
                url: step.url,
            })
        }
    }

    return (
        <div data-attr="action-type-switcher">
            <LemonSegmentedButton
                onChange={handleChange}
                value={
                    step.event === '$autocapture' || step.event === '$pageview' || step.event === undefined
                        ? step.event
                        : 'event'
                }
                options={[
                    {
                        value: '$pageview',
                        label: 'Pageview',
                        'data-attr': 'action-type-pageview',
                        disabledReason,
                    },
                    {
                        value: '$autocapture',
                        label: 'Autocapture',
                        'data-attr': 'action-type-autocapture',
                        disabledReason,
                    },
                    {
                        value: 'event',
                        label: 'Other events',
                        'data-attr': 'action-type-other',
                        disabledReason,
                    },
                ]}
                fullWidth
                size="small"
            />
        </div>
    )
}

function StringMatchingSelection({
    field,
    step,
    sendStep,
    disabledReason,
}: {
    field: 'url' | 'text' | 'href'
    step: ActionStepType
    sendStep: (stepToSend: ActionStepType) => void
    disabledReason?: string
}): JSX.Element {
    const key = `${field}_matching` as keyof ActionStepType
    const handleURLMatchChange = (value: string): void => {
        sendStep({ ...step, [key]: value })
    }
    const defaultValue: ActionStepStringMatching = field === 'url' ? 'contains' : 'exact'

    return (
        <div className="flex flex-1 justify-end">
            <LemonSegmentedButton
                onChange={handleURLMatchChange}
                value={(step[key] as ActionStepStringMatching) || defaultValue}
                options={[
                    {
                        value: 'exact',
                        label: 'matches exactly',
                        disabledReason,
                    },
                    {
                        value: 'regex',
                        label: 'matches regex',
                        disabledReason,
                    },
                    {
                        value: 'contains',
                        label: 'contains',
                        disabledReason,
                    },
                ]}
                size="xsmall"
            />
        </div>
    )
}
