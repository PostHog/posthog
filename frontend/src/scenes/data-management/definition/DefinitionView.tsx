import './Definition.scss'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { AvailableFeature } from '~/types'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { DefinitionPopup } from 'lib/components/DefinitionPopup/DefinitionPopup'
import {
    definitionLogic,
    DefinitionLogicProps,
    DefinitionPageMode,
} from 'scenes/data-management/definition/definitionLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { DefinitionEdit } from 'scenes/data-management/definition/DefinitionEdit'
import clsx from 'clsx'

export const scene: SceneExport = {
    component: DefinitionView,
    logic: definitionLogic,
    paramsToProps: ({ params: { id } }): typeof definitionLogic['props'] => ({
        id,
    }),
}

export function DefinitionView(props: DefinitionLogicProps = {}): JSX.Element {
    const logic = definitionLogic(props)
    const { definition, definitionLoading, singular, mode } = useValues(logic)
    const { setPageMode } = useActions(logic)
    const { hasAvailableFeature } = useValues(userLogic)

    return (
        <div className={clsx('definition-page', `definition-${mode}-page`)}>
            {mode === DefinitionPageMode.Edit ? (
                <DefinitionEdit {...props} />
            ) : (
                <>
                    <PageHeader
                        title={
                            <EditableField
                                name="name"
                                value={definition.name || ''}
                                placeholder={`Name this ${singular}`}
                                mode="view"
                                minLength={1}
                                maxLength={400} // Sync with action model
                                data-attr="definition-name-view"
                                className="definition-name"
                            />
                        }
                        caption={
                            <>
                                <EditableField
                                    multiline
                                    name="description"
                                    value={definition.description || ''}
                                    placeholder="Description (optional)"
                                    mode="view"
                                    data-attr="definition-description-view"
                                    className="definition-description"
                                    compactButtons
                                    maxLength={600}
                                    paywall={!hasAvailableFeature(AvailableFeature.INGESTION_TAXONOMY)}
                                />
                                <ObjectTags
                                    tags={definition.tags ?? []}
                                    data-attr="definition-tags-view"
                                    className="definition-tags"
                                    saving={definitionLoading}
                                />
                                <DefinitionPopup.TimeMeta
                                    createdAt={
                                        (definition && 'created_at' in definition && definition.created_at) || undefined
                                    }
                                    updatedAt={
                                        (definition && 'updated_at' in definition && definition.updated_at) || undefined
                                    }
                                    updatedBy={
                                        (definition && 'updated_by' in definition && definition.updated_by) || undefined
                                    }
                                />
                            </>
                        }
                        buttons={
                            <>
                                <LemonButton
                                    data-attr="edit-definition"
                                    type="secondary"
                                    style={{ marginRight: 8 }}
                                    onClick={() => {
                                        setPageMode(DefinitionPageMode.Edit)
                                    }}
                                >
                                    Edit
                                </LemonButton>
                            </>
                        }
                    />
                </>
            )}
        </div>
    )
}
