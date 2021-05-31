import { Button, Modal } from 'antd'
import React from 'react'
import { InsightType } from '~/types'
import { SaveOutlined, PlusOutlined, ShareAltOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { copyToClipboard } from 'lib/utils'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'

interface Props {
    shortId: string | null
    annotations: any[] // TODO: Type properly
    insight?: InsightType
    onReset?: () => void
}

export function InsightActionBar({ shortId, annotations, insight, onReset }: Props): JSX.Element {
    const { push } = useActions(router)
    const { reportInsightsTabReset } = useActions(eventUsageLogic)

    console.log(annotations)

    const handleShare = (): void => {
        // TODO: Prompt saving insight first
        copyToClipboard(`${window.location.origin}/i/${shortId}`, 'Share link')
    }

    const handleNew = (): void => {
        // TODO: UX improvemement. At a later point, we could implement an undo feature instead of prompting to confirm.
        Modal.confirm({
            title: 'Start fresh?',
            icon: <QuestionCircleOutlined />,
            content: 'This will clear any unsaved progress and start a new insight graph from scratch.',
            onOk() {
                window.scrollTo({ top: 0 })
                onReset ? onReset() : push(`/insights?insight=${insight}`)
                reportInsightsTabReset()
            },
        })
    }

    useKeyboardHotkeys({
        n: {
            action: handleNew,
        },
        k: {
            action: handleShare,
        },
    })

    return (
        <div className="insights-tab-actions">
            <Button type="link" icon={<PlusOutlined />} className="text-muted" onClick={handleNew}>
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
