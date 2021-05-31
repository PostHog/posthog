import { Button } from 'antd'
import React from 'react'
import { FilterType, InsightType } from '~/types'
import { SaveOutlined, PlusOutlined, ShareAltOutlined } from '@ant-design/icons'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { copyToClipboard } from 'lib/utils'

interface Props {
    shortId: string | null
    filters: FilterType
    annotations: any[] // TODO: Type properly
    insight?: InsightType
    onReset?: () => void
}

export function InsightActionBar({ shortId, filters, annotations, insight, onReset }: Props): JSX.Element {
    const { push } = useActions(router)
    const { reportInsightsTabReset } = useActions(eventUsageLogic)

    console.log(push, reportInsightsTabReset, filters, annotations, insight, onReset)

    const handleShare = (): void => {
        copyToClipboard(`${window.location.origin}/i/${shortId}`, 'Share link')
    }

    return (
        <div className="insights-tab-actions">
            <Button type="link" icon={<PlusOutlined />} className="text-muted">
                New
            </Button>
            <Button type="link" icon={<ShareAltOutlined />} onClick={handleShare} disabled={!shortId}>
                Share
            </Button>
            <Button type="link" icon={<SaveOutlined />}>
                Save
            </Button>
        </div>
    )
}
