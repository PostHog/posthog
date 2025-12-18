import { LogicWrapper, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCheck, IconPencil, IconPlus, IconTrash, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonInput, LemonLabel, lemonToast } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { cn } from 'lib/utils/css-classes'
import { AiRegexHelper, AiRegexHelperButton } from 'scenes/session-recordings/components/AiRegexHelper/AiRegexHelper'
import { Since } from 'scenes/settings/environment/SessionRecordingSettings'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { AccessControlAction } from '../../AccessControlAction'
import { ingestionControlsLogic } from '../ingestionControlsLogic'
import { UrlTriggerConfig } from '../types'

export function UrlConfig({
    logic,
    formKey,
    addUrl,
    validationWarning,
    title,
    description,
    checkUrl,
    checkUrlResults,
    setCheckUrl,
    ...props
}: {
    logic: LogicWrapper
    formKey: string
    addUrl: (urlTriggerConfig: UrlTriggerConfig) => void
    validationWarning: string | null
    title: string
    description: string
    checkUrl: string
    checkUrlResults: { [key: number]: boolean }
    setCheckUrl: (url: string) => void
    isAddFormVisible: boolean
    config: UrlTriggerConfig[] | null
    editIndex: number | null
    isSubmitting: boolean
    onAdd: () => void
    onCancel: () => void
    onEdit: (index: number) => void
    onRemove: (index: number) => void
}): JSX.Element {
    const { resourceType, logicKey } = useValues(ingestionControlsLogic)

    return (
        <div className="flex flex-col deprecated-space-y-2 mt-4">
            <div className="flex items-center gap-2 justify-between">
                <LemonLabel className="text-base">
                    {title} <Since web={{ version: '1.171.0' }} />
                </LemonLabel>
                <AccessControlAction resourceType={resourceType} minAccessLevel={AccessControlLevel.Editor}>
                    <LemonButton
                        onClick={props.onAdd}
                        type="secondary"
                        icon={<IconPlus />}
                        data-attr={`${logicKey}-add-url`}
                        size="small"
                    >
                        Add
                    </LemonButton>
                </AccessControlAction>
            </div>
            <p>{description}</p>

            {props.isAddFormVisible && (
                <UrlConfigForm
                    logic={logic}
                    formKey={formKey}
                    addUrl={addUrl}
                    validationWarning={validationWarning}
                    onCancel={props.onCancel}
                    isSubmitting={props.isSubmitting}
                />
            )}

            {!props.isAddFormVisible && props.config && props.config.length > 0 && (
                <div className="border rounded p-3 bg-surface-primary">
                    <LemonLabel className="text-sm font-medium mb-2 block">
                        Test a URL against these patterns:
                    </LemonLabel>
                    <LemonInput
                        value={checkUrl}
                        onChange={setCheckUrl}
                        placeholder="Enter a URL to test (e.g., https://example.com/page)"
                        data-attr="url-check-input"
                        className="mb-2"
                    />
                    {checkUrl && (
                        <div className="text-xs text-muted">
                            {Object.values(checkUrlResults).some(Boolean) ? (
                                <span className="text-success">✓ This URL matches at least one pattern</span>
                            ) : (
                                <span className="text-danger">✗ This URL doesn't match any patterns</span>
                            )}
                        </div>
                    )}
                </div>
            )}
            {props.config?.map((trigger, index) => (
                <UrlConfigRow
                    logic={logic}
                    formKey={formKey}
                    addUrl={addUrl}
                    validationWarning={validationWarning}
                    key={`${trigger.url}-${trigger.matching}`}
                    trigger={trigger}
                    index={index}
                    editIndex={props.editIndex}
                    onEdit={props.onEdit}
                    onRemove={props.onRemove}
                    checkUrlResult={checkUrlResults[index]}
                    resourceType={resourceType}
                />
            ))}
        </div>
    )
}

function UrlConfigRow({
    trigger,
    index,
    editIndex,
    onEdit,
    onRemove,
    checkUrlResult,
    logic,
    formKey,
    addUrl,
    validationWarning,
    resourceType,
}: {
    trigger: UrlTriggerConfig
    index: number
    editIndex: number | null
    onEdit: (index: number) => void
    onRemove: (index: number) => void
    checkUrlResult?: boolean
    logic: LogicWrapper
    formKey: string
    addUrl: (urlTriggerConfig: UrlTriggerConfig) => void
    validationWarning: string | null
    resourceType: AccessControlResourceType
}): JSX.Element {
    if (editIndex === index) {
        return (
            <div className="border rounded p-2 bg-surface-primary">
                <UrlConfigForm
                    logic={logic}
                    formKey={formKey}
                    addUrl={addUrl}
                    validationWarning={validationWarning}
                    onCancel={() => onEdit(-1)}
                    isSubmitting={false}
                />
            </div>
        )
    }

    return (
        <div
            className={cn('border rounded flex items-center p-2 pl-4 bg-surface-primary', {
                'border-success': checkUrlResult === true,
                'border-danger': checkUrlResult === false,
            })}
        >
            <span title={trigger.url} className="flex-1 truncate">
                <span>{trigger.matching === 'regex' ? 'Matches regex: ' : ''}</span>
                <span>{trigger.url}</span>
                {checkUrlResult !== undefined && (
                    <span
                        className={cn('ml-2 text-xs', {
                            'text-success': checkUrlResult === true,
                            'text-danger': checkUrlResult === false,
                        })}
                    >
                        {checkUrlResult ? (
                            <>
                                <IconCheck /> Matches
                            </>
                        ) : (
                            <>
                                <IconX /> No match
                            </>
                        )}
                    </span>
                )}
            </span>
            <div className="Actions flex deprecated-space-x-1 shrink-0">
                <AccessControlAction resourceType={resourceType} minAccessLevel={AccessControlLevel.Editor}>
                    <LemonButton icon={<IconPencil />} onClick={() => onEdit(index)} tooltip="Edit" center>
                        Edit
                    </LemonButton>
                </AccessControlAction>

                <AccessControlAction resourceType={resourceType} minAccessLevel={AccessControlLevel.Editor}>
                    <LemonButton
                        icon={<IconTrash />}
                        tooltip="Remove URL"
                        center
                        onClick={() => {
                            LemonDialog.open({
                                title: <>Remove URL</>,
                                description: 'Are you sure you want to remove this URL?',
                                primaryButton: {
                                    status: 'danger',
                                    children: 'Remove',
                                    onClick: () => onRemove(index),
                                },
                                secondaryButton: {
                                    children: 'Cancel',
                                },
                            })
                        }}
                    >
                        Remove
                    </LemonButton>
                </AccessControlAction>
            </div>
        </div>
    )
}

function UrlConfigForm({
    onCancel,
    isSubmitting,
    logic,
    formKey,
    validationWarning,
    addUrl,
}: {
    onCancel: () => void
    isSubmitting: boolean
    logic: LogicWrapper
    formKey: string
    addUrl: (urlTriggerConfig: UrlTriggerConfig) => void
    validationWarning: string | null
}): JSX.Element {
    return (
        <Form
            logic={logic}
            formKey={formKey}
            enableFormOnSubmit
            className="w-full flex flex-col border rounded items-center p-2 pl-4 bg-surface-primary gap-2"
        >
            <div className="flex flex-col gap-2 w-full">
                <LemonBanner type="info" className="text-sm">
                    We always wrap the URL regex with anchors to avoid unexpected behavior (if you do not). This is
                    because <pre className="inline">https://example.com/</pre> does not only match the homepage. You'd
                    need <pre className="inline">^https://example.com/$</pre>
                </LemonBanner>
                <LemonLabel className="w-full">
                    Matching regex:
                    <LemonField name="url" className="flex-1">
                        <LemonInput autoFocus placeholder="Enter URL regex." data-attr="url-input" />
                    </LemonField>
                </LemonLabel>
                {validationWarning && <span className="text-danger">{validationWarning}</span>}
            </div>
            <div className="flex justify-between gap-2 w-full">
                <div>
                    <AiRegexHelper
                        onApply={(regex) => {
                            try {
                                addUrl({
                                    url: regex,
                                    matching: 'regex',
                                })
                            } catch {
                                lemonToast.error('Failed to apply regex')
                            }
                        }}
                    />
                    <AiRegexHelperButton />
                </div>

                <div className="flex gap-2">
                    <LemonButton type="secondary" onClick={onCancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        htmlType="submit"
                        type="primary"
                        disabledReason={isSubmitting ? `Saving url in progress` : undefined}
                        data-attr="url-save"
                    >
                        Save
                    </LemonButton>
                </div>
            </div>
        </Form>
    )
}
