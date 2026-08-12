import { LogicWrapper, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCheck, IconPencil, IconPlus, IconTrash, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonInput, LemonLabel, lemonToast } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { cn } from 'lib/utils/css-classes'
import { AiRegexHelper, AiRegexHelperButton } from 'scenes/session-recordings/components/AiRegexHelper/AiRegexHelper'
import { Since } from 'scenes/settings/environment/SessionRecordingSettings'

import { ingestionControlsLogic } from '../ingestionControlsLogic'
import { UrlTriggerConfig } from '../types'
import { UrlPatternTestRow, UrlPatternTestStatus } from './urlConfigLogic'

export function UrlConfig({
    logic,
    logicProps,
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
    logicProps: Record<string, any>
    formKey: string
    addUrl: (urlTriggerConfig: UrlTriggerConfig) => void
    validationWarning: string | null
    title: string
    description: string
    checkUrl: string
    checkUrlResults: UrlPatternTestRow[]
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
    const { logicKey } = useValues(ingestionControlsLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    // Saved patterns keep their config order in the results, so index maps straight to each row.
    const savedStatuses = checkUrlResults.filter((row) => !row.inProgress).map((row) => row.status)

    return (
        <div className="flex flex-col gap-y-2">
            <div className="flex items-center gap-2 justify-between">
                <LemonLabel className="text-base">
                    {title} <Since web={{ version: '1.171.0' }} />
                </LemonLabel>
                <LemonButton
                    onClick={props.onAdd}
                    type="secondary"
                    icon={<IconPlus />}
                    data-attr={`${logicKey}-add-url`}
                    size="small"
                    disabledReason={restrictedReason}
                >
                    Add
                </LemonButton>
            </div>
            <p>{description}</p>

            {props.isAddFormVisible && (
                <UrlConfigForm
                    logic={logic}
                    logicProps={logicProps}
                    formKey={formKey}
                    addUrl={addUrl}
                    validationWarning={validationWarning}
                    onCancel={props.onCancel}
                    isSubmitting={props.isSubmitting}
                />
            )}

            {((props.config?.length ?? 0) > 0 || props.isAddFormVisible) && (
                <UrlPatternTester checkUrl={checkUrl} setCheckUrl={setCheckUrl} results={checkUrlResults} />
            )}
            {props.config?.map((trigger, index) => (
                <UrlConfigRow
                    logic={logic}
                    logicProps={logicProps}
                    formKey={formKey}
                    addUrl={addUrl}
                    validationWarning={validationWarning}
                    key={`${trigger.url}-${trigger.matching}`}
                    trigger={trigger}
                    index={index}
                    editIndex={props.editIndex}
                    onEdit={props.onEdit}
                    onRemove={props.onRemove}
                    checkUrlStatus={savedStatuses[index]}
                />
            ))}
        </div>
    )
}

export function UrlPatternTester({
    checkUrl,
    setCheckUrl,
    results,
}: {
    checkUrl: string
    setCheckUrl: (url: string) => void
    results: UrlPatternTestRow[]
}): JSX.Element {
    const anyMatch = results.some((row) => row.status === 'match')
    const anyInvalid = results.some((row) => row.status === 'invalid')
    const matchedPatterns = results.filter((row) => row.status === 'match').map((row) => row.pattern)
    const inProgressRow = results.find((row) => row.inProgress)

    return (
        <div className="border rounded p-3 bg-surface-primary">
            <LemonLabel className="text-sm font-medium mb-2 block">
                Test a URL against these regular expressions
            </LemonLabel>
            <LemonInput
                value={checkUrl}
                onChange={setCheckUrl}
                placeholder="Enter a URL to test (e.g., https://example.com/page)"
                data-attr="url-check-input"
                className="mb-2"
            />
            {checkUrl && (
                <div className="text-xs flex flex-col gap-1">
                    {anyMatch ? (
                        <span className="text-success">
                            ✓ Matches:{' '}
                            {matchedPatterns.map((pattern, i) => (
                                <span key={pattern}>
                                    {i > 0 ? ', ' : ''}
                                    <code>{pattern}</code>
                                </span>
                            ))}
                        </span>
                    ) : (
                        <span className="text-danger">✗ No pattern matches this URL</span>
                    )}
                    {inProgressRow && (
                        <span className="text-muted">
                            New pattern <code>{inProgressRow.pattern}</code>{' '}
                            {inProgressRow.status === 'match'
                                ? 'matches this URL'
                                : inProgressRow.status === 'invalid'
                                  ? 'is not a valid regular expression'
                                  : "doesn't match this URL"}
                        </span>
                    )}
                    {anyInvalid && (
                        <span className="text-danger">
                            One or more patterns are not valid regular expressions, so they never match. Edit them to
                            fix this.
                        </span>
                    )}
                </div>
            )}
        </div>
    )
}

function UrlConfigRow({
    trigger,
    index,
    editIndex,
    onEdit,
    onRemove,
    checkUrlStatus,
    logic,
    logicProps,
    formKey,
    addUrl,
    validationWarning,
}: {
    trigger: UrlTriggerConfig
    index: number
    editIndex: number | null
    onEdit: (index: number) => void
    onRemove: (index: number) => void
    checkUrlStatus?: UrlPatternTestStatus
    logic: LogicWrapper
    logicProps: Record<string, any>
    formKey: string
    addUrl: (urlTriggerConfig: UrlTriggerConfig) => void
    validationWarning: string | null
}): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    if (editIndex === index) {
        return (
            <div className="border rounded p-2 bg-surface-primary">
                <UrlConfigForm
                    logic={logic}
                    logicProps={logicProps}
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
                'border-success': checkUrlStatus === 'match',
                'border-danger': checkUrlStatus === 'no-match' || checkUrlStatus === 'invalid',
            })}
        >
            <span title={trigger.url} className="flex-1 truncate">
                <span>{trigger.matching === 'regex' ? 'Matches regex: ' : ''}</span>
                <span>{trigger.url}</span>
                {checkUrlStatus !== undefined && (
                    <span
                        className={cn('ml-2 text-xs', {
                            'text-success': checkUrlStatus === 'match',
                            'text-danger': checkUrlStatus === 'no-match' || checkUrlStatus === 'invalid',
                        })}
                    >
                        {checkUrlStatus === 'match' ? (
                            <>
                                <IconCheck /> Matches
                            </>
                        ) : checkUrlStatus === 'invalid' ? (
                            <>
                                <IconX /> Invalid pattern — never matches
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
                <LemonButton
                    icon={<IconPencil />}
                    onClick={() => onEdit(index)}
                    tooltip="Edit"
                    center
                    disabledReason={restrictedReason}
                >
                    Edit
                </LemonButton>

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
                    disabledReason={restrictedReason}
                >
                    Remove
                </LemonButton>
            </div>
        </div>
    )
}

function UrlConfigForm({
    onCancel,
    isSubmitting,
    logic,
    logicProps,
    formKey,
    validationWarning,
    addUrl,
}: {
    onCancel: () => void
    isSubmitting: boolean
    logic: LogicWrapper
    logicProps: Record<string, any>
    formKey: string
    addUrl: (urlTriggerConfig: UrlTriggerConfig) => void
    validationWarning: string | null
}): JSX.Element {
    return (
        <Form
            logic={logic}
            props={logicProps}
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
