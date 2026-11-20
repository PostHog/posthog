import { Button, Card, CardContent, Item, ItemContent, ItemDescription } from '@posthog/quill'

import { ImportStatus } from '../ImportStatusHeader/ImportStatusHeader'
import { QuillImportStatusHeader } from '../QuillImportStatusHeader/QuillImportStatusHeader'
import { QuillSettingsSubsection } from '../QuillSettingsSubsection/QuillSettingsSubsection'

export function QuillImportSection({
    title,
    description,
    status,
    progressLabel,
    latestError,
    completedSummary,
    warning,
    children,
    onStartImport,
    startLoading,
    startDisabledReason,
}: {
    title: string
    description: string
    status: ImportStatus | undefined
    progressLabel: string | null
    latestError: string | null | undefined
    completedSummary: React.ReactNode
    warning: React.ReactNode
    children: React.ReactNode
    onStartImport: () => void
    startLoading: boolean
    startDisabledReason: string | null | undefined
}): JSX.Element {
    return (
        <QuillSettingsSubsection title={title} description={description}>
            <Card size="sm" className="max-w-200">
                <CardContent className="flex flex-col gap-3">
                    <QuillImportStatusHeader status={status} progressLabel={progressLabel} latestError={latestError} />
                    {status === 'completed' ? completedSummary : null}
                    {children}
                    {warning ? (
                        <Item tone="warning" size="sm">
                            <ItemContent>
                                <ItemDescription>{warning}</ItemDescription>
                            </ItemContent>
                        </Item>
                    ) : null}
                    <div>
                        <Button
                            variant="primary"
                            onClick={onStartImport}
                            loading={startLoading}
                            disabledReason={startDisabledReason}
                        >
                            Start import
                        </Button>
                    </div>
                </CardContent>
            </Card>
        </QuillSettingsSubsection>
    )
}
