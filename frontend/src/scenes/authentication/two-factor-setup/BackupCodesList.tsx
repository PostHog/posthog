import { IconCopy } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

export function BackupCodesList({ codes }: { codes: string[] }): JSX.Element {
    return (
        <div className="ph-no-capture bg-primary p-4 rounded font-mono deprecated-space-y-1 relative">
            <LemonButton
                icon={<IconCopy />}
                size="small"
                className="absolute top-4 right-4"
                data-attr="2fa-copy-backup-codes"
                onClick={() => {
                    void copyToClipboard(codes.join('\n'), 'backup codes')
                }}
            >
                Copy
            </LemonButton>
            {codes.map((code) => (
                <div key={code}>{code}</div>
            ))}
        </div>
    )
}
