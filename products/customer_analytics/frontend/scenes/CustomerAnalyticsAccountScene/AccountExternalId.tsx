import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

export function AccountExternalId({ externalId }: { externalId: string }): JSX.Element {
    return (
        <div className="flex items-center gap-1 min-w-0" data-attr="account-external-id">
            <span className="text-secondary shrink-0">External ID:</span>
            <CopyToClipboardInline explicitValue={externalId} description="external ID" iconSize="xsmall">
                {externalId}
            </CopyToClipboardInline>
        </div>
    )
}
