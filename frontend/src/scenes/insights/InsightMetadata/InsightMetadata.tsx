import './InsightMetadata.scss'
import React from 'react'
import { DashboardItemType } from '~/types'
import { Button, Input } from 'antd'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ObjectTags } from 'lib/components/ObjectTags'
import clsx from 'clsx'
import { insightMetadataLogic } from 'scenes/insights/InsightMetadata/insightMetadataLogic'
import { EditOutlined } from '@ant-design/icons'

function createInsightInputClassName(type: string, isEditable: boolean): string {
    return clsx('insight-metadata-input', `insight-metadata-${type}`, { edit: isEditable })
}

interface Props {
    insight: Partial<DashboardItemType>
    isEditable?: boolean
}

function Title({ insight, isEditable = false }: Props): JSX.Element {
    const property = 'name'
    const logic = insightMetadataLogic({ insight: { [property]: insight[property] || '' } })
    const { insightMetadata, editableProps } = useValues(logic)
    const { setInsightMetadata, updateInsightMetadata, showEditMode, showViewMode } = useActions(logic)
    const placeholder = insight[property] || `Insight #${insight.id ?? '...'}`

    return (
        <div className={createInsightInputClassName('title', isEditable)} data-attr="insight-title">
            {isEditable ? (
                editableProps.has(property) ? (
                    <Input
                        placeholder={placeholder}
                        value={insightMetadata[property]}
                        size="large"
                        onChange={(e) => {
                            setInsightMetadata({ [property]: e.target.value })
                        }}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                                updateInsightMetadata(insight)
                            }
                        }}
                        tabIndex={0}
                        suffix={
                            <>
                                <Button className="btn-cancel" size="small" onClick={() => showViewMode(property)}>
                                    Cancel
                                </Button>
                                <Button className="ml-025" type="primary" size="small">
                                    Done
                                </Button>
                            </>
                        }
                    />
                ) : (
                    <>
                        <span className="title">{placeholder}</span>
                        <Button
                            type="link"
                            onClick={() => {
                                showEditMode(property)
                            }}
                            className="btn-edit"
                            data-attr={`edit-prop-${property}`}
                            title={`Edit ${property}`}
                        >
                            <EditOutlined />
                        </Button>
                    </>
                )
            ) : (
                <span className="title">{placeholder}</span>
            )}
        </div>
    )
}

function Description({ insight, isEditable = false }: Props): JSX.Element | null {
    const logic = insightMetadataLogic({ insight: { description: insight.description } })
    const { insightMetadata } = useValues(logic)
    const { setInsightMetadata, updateInsightMetadata } = useActions(logic)

    if (!insight.description && !isEditable) {
        return null
    }

    return (
        <div className={createInsightInputClassName('description', isEditable)} data-attr="insight-description">
            {isEditable ? (
                <Input.TextArea
                    className="insight-description-textarea ant-input-lg" // hack needed because antd's textarea doesn't support size api
                    style={{ padding: '6.5px 11px' }}
                    value={insightMetadata.description}
                    onChange={(e) => {
                        setInsightMetadata({ description: e.target.value })
                    }}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                            updateInsightMetadata(insight)
                        }
                    }}
                    tabIndex={5}
                    autoSize={{ minRows: 1, maxRows: 5 }}
                />
            ) : (
                <span className="description">{insightMetadata.description ?? insight.description}</span>
            )}
        </div>
    )
}

function Tags({ insight, isEditable = false }: Props): JSX.Element | null {
    const { saveNewTag, deleteTag } = useActions(insightLogic)
    const { tagLoading } = useValues(insightLogic)

    if ((insight.tags ?? []).length === 0 && !isEditable) {
        return null
    }

    return (
        <div className={createInsightInputClassName('tags', isEditable)} data-attr="insight-tags">
            {isEditable ? (
                <ObjectTags
                    tags={insight.tags ?? []}
                    onTagSave={saveNewTag}
                    onTagDelete={deleteTag}
                    saving={tagLoading}
                    tagsAvailable={[]}
                />
            ) : (
                <ObjectTags tags={insight.tags ?? []} staticOnly />
            )}
        </div>
    )
}

export const InsightMetadata = {
    Title,
    Description,
    Tags,
}
