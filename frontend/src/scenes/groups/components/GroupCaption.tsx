import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'

import { Group } from '~/types'

interface GroupCaptionProps {
    groupData: Group
    groupTypeName: string
}

export function GroupCaption({ groupData, groupTypeName }: GroupCaptionProps): JSX.Element {
    return (
        <div className="flex items-center flex-wrap">
            <div className="mr-4">
                <span className="text-secondary">Type:</span> {groupTypeName}
            </div>
            <div className="mr-4">
                <span className="text-secondary">Key:</span>{' '}
                <CopyToClipboardInline
                    tooltipMessage={null}
                    description="group key"
                    style={{ display: 'inline-flex', justifyContent: 'flex-end' }}
                >
                    {groupData.group_key}
                </CopyToClipboardInline>
            </div>
            <div>
                <span className="text-secondary">First seen:</span>{' '}
                {groupData.created_at ? <TZLabel time={groupData.created_at} /> : 'unknown'}
            </div>
        </div>
    )
}
