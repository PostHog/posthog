import './InsightMetadata.scss'
import React from 'react'
import { AvailableFeature, DashboardItemType, ItemMode } from '~/types'
import { Button, Input } from 'antd'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ObjectTags } from 'lib/components/ObjectTags'
import { insightMetadataLogic } from 'scenes/insights/InsightMetadata/insightMetadataLogic'
import { EditOutlined } from '@ant-design/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'
import { FEATURE_FLAGS } from 'lib/constants'

function createInsightInputClassName(type: string): string {
    return `insight-metadata-input insight-metadata-${type}`
}

interface MetadataProps {
    insight: Partial<DashboardItemType>
    insightMode: ItemMode
}

function Title({ insight, insightMode }: MetadataProps): JSX.Element {
    const property = 'name'
    const { insightProps } = useValues(insightLogic)
    const logic = insightMetadataLogic({ insightProps, insight: { [property]: insight?.[property] } })
    const { editableProps, isEditable } = useValues(logic)
    const { setInsightMetadata, saveInsightMetadata, cancelInsightMetadata, showEditMode } = useActions(logic)
    const placeholder = insight[property] ?? `Insight #${insight.id ?? '...'}`

    return (
        <div className={createInsightInputClassName('title')} data-attr="insight-title">
            {isEditable && editableProps.has(property) ? (
                <Input
                    placeholder={`Insight #${insight.id ?? '...'}`}
                    defaultValue={insight[property] ?? ''}
                    size="large"
                    onChange={(e) => {
                        setInsightMetadata({ [property]: e.target.value })
                    }}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            saveInsightMetadata(property, false)
                        }
                    }}
                    tabIndex={0}
                    suffix={
                        <>
                            <Button className="btn-cancel" size="small" onClick={() => cancelInsightMetadata(property)}>
                                Cancel
                            </Button>
                            <Button
                                className="ml-025"
                                type="primary"
                                size="small"
                                onClick={() => saveInsightMetadata(property, insightMode !== ItemMode.Edit)}
                            >
                                Done
                            </Button>
                        </>
                    }
                />
            ) : (
                <>
                    <span className="title">{placeholder}</span>
                    {isEditable && (
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
                    )}
                </>
            )}
        </div>
    )
}

function Description({ insight, insightMode }: MetadataProps): JSX.Element | null {
    const property = 'description'
    const { insightProps } = useValues(insightLogic)
    const logic = insightMetadataLogic({ insightProps, insight: { [property]: insight?.[property] } })
    const { editableProps, isEditable } = useValues(logic)
    const { setInsightMetadata, saveInsightMetadata, showEditMode, cancelInsightMetadata } = useActions(logic)

    if (!isEditable) {
        return null
    }

    return (
        <div className={createInsightInputClassName('description')} data-attr="insight-description">
            {isEditable && editableProps.has(property) ? (
                <div className="ant-input-affix-wrapper ant-input-affix-wrapper-lg insight-description-textarea-wrapper">
                    <Input.TextArea
                        className="insight-description-textarea" // hack needed because antd's textarea doesn't support size api
                        placeholder={`Description`}
                        defaultValue={insight[property] ?? ''}
                        onChange={(e) => {
                            setInsightMetadata({ [property]: e.target.value })
                        }}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                                saveInsightMetadata(property, false)
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
                        onClick={() => saveInsightMetadata(property, insightMode !== ItemMode.Edit)}
                    >
                        Done
                    </Button>
                </div>
            ) : (
                <>
                    <span className="description">{insight[property] ?? 'Description (optional)'}</span>
                    {isEditable && (
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
                    )}
                </>
            )}
        </div>
    )
}

function Tags({ insight }: MetadataProps): JSX.Element | null {
    const { saveNewTag, deleteTag } = useActions(insightLogic)
    const { tagLoading } = useValues(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { user } = useValues(userLogic)
    // TODO: this needs to be put back in insightMetadataLogic, but after out-of-scope refactors
    const isEditable = !!(
        featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS] &&
        user?.organization?.available_features?.includes(AvailableFeature.DASHBOARD_COLLABORATION)
    )

    if (!isEditable) {
        return null
    }

    return (
        <div className={createInsightInputClassName('tags')} data-attr="insight-tags">
            <ObjectTags
                tags={insight.tags ?? []}
                onTagSave={saveNewTag}
                onTagDelete={deleteTag}
                saving={tagLoading}
                tagsAvailable={[]}
            />
        </div>
    )
}

export const InsightMetadata = {
    Title,
    Description,
    Tags,
}
