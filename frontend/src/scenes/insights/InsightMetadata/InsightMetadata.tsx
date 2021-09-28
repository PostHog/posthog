import './InsightMetadata.scss'
import React from 'react'
import { DashboardItemType } from '~/types'
import { Input } from 'antd'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ObjectTags } from 'lib/components/ObjectTags'

interface Props {
    insight: Partial<DashboardItemType>
    isEditable?: boolean
}

function Title({ insight, isEditable = false }: Props): JSX.Element {
    const { updateInsight, setInsight } = useActions(insightLogic)

    return (
        <div className="insight-metadata-input insight-metadata-title">
            {isEditable ? (
                <Input
                    data-attr="insight-title"
                    placeholder={insight.name || `Insight #${insight.id ?? '...'}`}
                    value={insight.name || ''}
                    size="large"
                    onChange={(e) => setInsight({ ...insight, name: e.target.value })}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            updateInsight(insight)
                        }
                    }}
                    tabIndex={0}
                />
            ) : (
                <span className="title" data-attr="insight-title">
                    {insight.name || `Insight #${insight.id ?? '...'}`}
                </span>
            )}
        </div>
    )
}

function Description({ insight, isEditable = false }: Props): JSX.Element | null {
    const { updateInsight, setInsight } = useActions(insightLogic)

    if (!insight.description && !isEditable) {
        return null
    }

    return (
        <div className="insight-metadata-input insight-metadata-description">
            {isEditable ? (
                <Input.TextArea
                    data-attr="insight-description"
                    className="insight-description-textarea"
                    style={{ padding: '6.5px 11px' }}
                    value={insight.description}
                    onChange={(e) => setInsight({ ...insight, description: e.target.value })}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                            updateInsight(insight)
                        }
                    }}
                    tabIndex={5}
                    allowClear
                    autoSize={{ minRows: 1, maxRows: 5 }}
                />
            ) : (
                <span className="description" data-attr="insight-description">
                    {insight.description}
                </span>
            )}
        </div>
    )
}

function Tags({ insight, isEditable = false }: Props): JSX.Element | null {
    const { saveNewTag, deleteTag } = useActions(insightLogic)
    const { tagLoading } = useValues(insightLogic)

    console.log('TAGS', insight)

    if ((insight.tags ?? []).length === 0 && !isEditable) {
        return null
    }

    return (
        <div className="insight-metadata-input insight-metadata-tags">
            {isEditable ? (
                <ObjectTags
                    tags={insight.tags ?? []}
                    onTagSave={saveNewTag}
                    onTagDelete={deleteTag}
                    saving={tagLoading}
                    tagsAvailable={[]}
                />
            ) : (
                <div className="tags" data-attr="insight-tags">
                    <ObjectTags tags={insight.tags ?? []} staticOnly />
                </div>
            )}
        </div>
    )
}

export const InsightMetadata = {
    Title,
    Description,
    Tags,
}
