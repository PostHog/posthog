import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonCollapse,
    LemonDialog,
    LemonLabel,
    LemonSkeleton,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

export interface SupportPlaybookEditorProps {
    inheritedInstructions: string
    draft: string
    isCustomized: boolean
    maxChars: number
    saving: boolean
    loading: boolean
    error: string | null
    dirty: boolean
    onDraftChange: (value: string) => void
    onSave: () => void
    onReset: () => void
}

export function SupportPlaybookEditor({
    inheritedInstructions,
    draft,
    isCustomized,
    maxChars,
    saving,
    loading,
    error,
    dirty,
    onDraftChange,
    onSave,
    onReset,
}: SupportPlaybookEditorProps): JSX.Element {
    if (loading && !inheritedInstructions) {
        return (
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                <LemonSkeleton className="h-4 w-40" />
                <LemonSkeleton className="h-24 w-full" />
            </LemonCard>
        )
    }

    if (error && !inheritedInstructions) {
        return (
            <LemonBanner type="error" className="max-w-[800px]">
                {error}
            </LemonBanner>
        )
    }

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
            <div className="flex flex-wrap items-center gap-2 justify-between">
                <LemonTag type={isCustomized ? 'primary' : 'muted'}>
                    {isCustomized ? 'Customized' : 'Using default instructions'}
                </LemonTag>
                {isCustomized && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => {
                            LemonDialog.open({
                                title: 'Reset to default instructions?',
                                description:
                                    'This removes your team instructions. Replies will use the default playbook again.',
                                primaryButton: {
                                    children: 'Reset',
                                    type: 'primary',
                                    onClick: onReset,
                                    size: 'small',
                                },
                                secondaryButton: {
                                    children: 'Cancel',
                                    type: 'tertiary',
                                    size: 'small',
                                },
                            })
                        }}
                        loading={saving}
                        disabledReason={saving ? 'Saving…' : undefined}
                        data-attr="support-playbook-reset"
                    >
                        Reset to default
                    </LemonButton>
                )}
            </div>
            {inheritedInstructions ? (
                <LemonCollapse
                    defaultActiveKey={isCustomized ? undefined : 'inherited'}
                    panels={[
                        {
                            key: 'inherited',
                            header: 'Default instructions',
                            content: (
                                <pre className="text-xs whitespace-pre-wrap m-0 text-muted-alt">
                                    {inheritedInstructions}
                                </pre>
                            ),
                        },
                    ]}
                />
            ) : null}
            <div>
                <LemonLabel htmlFor="support-playbook-editor">Team instructions</LemonLabel>
                <LemonTextArea
                    id="support-playbook-editor"
                    value={draft}
                    onChange={onDraftChange}
                    placeholder="Optional extra instructions for your team"
                    minRows={6}
                    maxRows={24}
                    maxLength={maxChars}
                    disabled={saving}
                    data-attr="support-playbook-editor"
                />
            </div>
            <div>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={onSave}
                    loading={saving}
                    disabledReason={saving ? 'Saving…' : !dirty ? 'No changes to save' : undefined}
                    data-attr="support-playbook-save"
                >
                    Save playbook
                </LemonButton>
            </div>
        </LemonCard>
    )
}
