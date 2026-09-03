import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

export function AccountCaption({ externalId }: { externalId: string | null }): JSX.Element {
    return (
        <div className="flex items-center flex-wrap" data-attr="account-caption">
            <span className="text-secondary mr-1">External ID:</span>
            {externalId ? (
                <CopyToClipboardInline
                    explicitValue={externalId}
                    tooltipMessage={null}
                    description="external ID"
                    className="font-mono"
                >
                    {externalId}
                </CopyToClipboardInline>
            ) : (
                <span className="text-muted">Not set</span>
            )}
        </div>
    )
}
