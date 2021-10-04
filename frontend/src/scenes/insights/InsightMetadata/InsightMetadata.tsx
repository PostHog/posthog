import './InsightMetadata.scss'
import React, { useEffect } from 'react'
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

function useUpdateMetadata(
    value: any,
    property: keyof DashboardItemType,
    setProperty: (insight: Partial<DashboardItemType>) => void
): void {
    // Unfortunately there's no way around this. See ActionFilter for similar behavior.
    useEffect(() => {
        setProperty({ [property]: value })
    }, [value])
}

interface MetadataProps {
    insight: Partial<DashboardItemType>
    isEditable?: boolean
}

function Title({ insight, isEditable = false }: MetadataProps): JSX.Element {
    const property = 'name'
    const logic = insightMetadataLogic({ insight: { [property]: insight?.[property] } })
    const { editableProps } = useValues(logic)
    const { setInsightMetadata, saveInsightMetadata, cancelInsightMetadata, showEditMode } = useActions(logic)
    const placeholder = insight[property] ?? `Insight #${insight.id ?? '...'}`

    useUpdateMetadata(insight?.[property], property, setInsightMetadata)

    return (
        <div className={createInsightInputClassName('title', isEditable)} data-attr="insight-title">
            {isEditable ? (
                editableProps.has(property) ? (
                    <Input
                        placeholder={insight[property] ?? `Insight #${insight.id ?? '...'}`}
                        defaultValue={insight[property] ?? ''}
                        size="large"
                        onChange={(e) => {
                            setInsightMetadata({ [property]: e.target.value })
                        }}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                                saveInsightMetadata(property)
                            }
                        }}
                        tabIndex={0}
                        suffix={
                            <>
                                <Button
                                    className="btn-cancel"
                                    size="small"
                                    onClick={() => cancelInsightMetadata(property)}
                                >
                                    Cancel
                                </Button>
                                <Button
                                    className="ml-025"
                                    type="primary"
                                    size="small"
                                    onClick={() => saveInsightMetadata(property)}
                                >
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

function Description({ insight, isEditable = false }: MetadataProps): JSX.Element | null {
    const property = 'description'
    const logic = insightMetadataLogic({ insight: { [property]: insight?.[property] } })
    const { editableProps } = useValues(logic)
    const { setInsightMetadata, saveInsightMetadata, showEditMode, cancelInsightMetadata } = useActions(logic)

    useUpdateMetadata(insight?.[property], property, setInsightMetadata)

    if (!insight[property] && !isEditable) {
        return null
    }

    return (
        <div className={createInsightInputClassName('description', isEditable)} data-attr="insight-description">
            {isEditable ? (
                editableProps.has(property) ? (
                    <div className="ant-input-affix-wrapper ant-input-affix-wrapper-lg insight-description-textarea-wrapper">
                        <Input.TextArea
                            className="insight-description-textarea" // hack needed because antd's textarea doesn't support size api
                            placeholder={insight[property] ?? `Description`}
                            defaultValue={insight[property] ?? ''}
                            onChange={(e) => {
                                setInsightMetadata({ [property]: e.target.value })
                            }}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                                    saveInsightMetadata(property)
                                }
                            }}
                            tabIndex={5}
                            autoSize={{ minRows: 1, maxRows: 5 }}
                        />
                        <Button className="btn-cancel" size="small" onClick={() => cancelInsightMetadata(property)}>
                            Cancel
                        </Button>
                        <Button
                            className="ml-025"
                            type="primary"
                            size="small"
                            onClick={() => saveInsightMetadata(property)}
                        >
                            Done
                        </Button>
                    </div>
                ) : (
                    <>
                        <span className="description">{insight[property] ?? 'Description (optional)'}</span>
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
                <span className="description">{insight[property]}</span>
            )}
        </div>
    )
}

function Tags({ insight, isEditable = false }: MetadataProps): JSX.Element | null {
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
