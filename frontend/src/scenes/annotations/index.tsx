import React, { useState, useEffect, HTMLAttributes } from 'react'
import { useValues, useActions } from 'kea'
import { annotationsModel } from '~/models/annotationsModel'
import { annotationsTableLogic } from './logic'

import { PageHeader } from 'lib/components/PageHeader'
import { AnnotationType, AnnotationScope } from '~/types'
import { SceneExport } from 'scenes/sceneTypes'
import { dayjs } from 'lib/dayjs'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { LemonTable, LemonTableColumns, LemonTableColumn } from 'lib/components/LemonTable'
import { createdByColumn } from 'lib/components/LemonTable/columnUtils'
import { TZLabel } from 'lib/components/TimezoneAware'
import { LemonButton } from 'lib/components/LemonButton'
import { DatePicker } from 'lib/components/DatePicker'
import { LemonModal } from 'lib/components/LemonModal'
import { LemonSelect } from 'lib/components/LemonSelect'
import { LemonTextArea } from 'lib/components/LemonTextArea/LemonTextArea'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'

export const scene: SceneExport = {
    component: Annotations,
    logic: annotationsTableLogic,
}

export function Annotations(): JSX.Element {
    const { annotations, annotationsLoading, next, loadingNext } = useValues(annotationsTableLogic)
    const { updateAnnotation, deleteAnnotation, loadAnnotationsNext, restoreAnnotation } =
        useActions(annotationsTableLogic)
    const { createGlobalAnnotation } = useActions(annotationsModel)
    const [open, setOpen] = useState(false)
    const [selectedAnnotation, setSelected] = useState(null as AnnotationType | null)

    const columns: LemonTableColumns<AnnotationType> = [
        {
            title: 'Annotation',
            key: 'annotation',
            width: '30%',
            render: function RenderAnnotation(_, annotation: AnnotationType): JSX.Element {
                return <div className="ph-no-capture">{annotation.content}</div>
            },
        },
        {
            title: 'For date',
            dataIndex: 'date_marker',
            render: function RenderDateMarker(_, annotation: AnnotationType): JSX.Element {
                return <span>{dayjs(annotation.date_marker).format('MMMM DD, YYYY')}</span>
            },
            sorter: (a, b) => dayjs(a.date_marker).diff(b.date_marker),
        },
        createdByColumn() as LemonTableColumn<AnnotationType, keyof AnnotationType | undefined>,
        {
            title: 'Last updated',
            dataIndex: 'updated_at',
            render: function RenderLastUpdated(_, annotation: AnnotationType): JSX.Element {
                return <TZLabel time={annotation.updated_at} />
            },
            sorter: (a, b) => dayjs(a.date_marker).diff(b.date_marker),
        },
        {
            title: 'Status',
            render: function RenderStatus(_, annotation: AnnotationType): JSX.Element {
                return annotation.deleted ? (
                    <LemonTag type="danger">Deleted</LemonTag>
                ) : (
                    <LemonTag type="success">Active</LemonTag>
                )
            },
        },
        {
            title: 'Scope',
            render: function RenderType(_, annotation: AnnotationType): JSX.Element {
                return annotation.scope === AnnotationScope.Insight ? (
                    <LemonTag
                        className="border"
                        style={{
                            // overriding tag color here to match antd for now
                            color: '#096dd9',
                            background: '#e6f7ff',
                            borderColor: '#91d5ff',
                        }}
                    >
                        Insight
                    </LemonTag>
                ) : annotation.scope === AnnotationScope.Project ? (
                    <LemonTag
                        className="border"
                        style={{
                            // overriding tag color here to match antd for now
                            color: '#531dab',
                            background: '#f9f0ff',
                            borderColor: '#d3adf7',
                        }}
                    >
                        Project
                    </LemonTag>
                ) : annotation.scope === AnnotationScope.Organization ? (
                    <LemonTag
                        className="border"
                        style={{
                            // overriding tag color here to match antd for now
                            color: '#c41d7f',
                            background: '#fff0f6',
                            borderColor: '#ffadd2',
                        }}
                    >
                        Organization
                    </LemonTag>
                ) : (
                    <LemonTag>Unknown ({annotation.scope})</LemonTag>
                )
            },
        },
    ]

    function closeModal(): void {
        setOpen(false)
        setTimeout(() => setSelected(null as AnnotationType | null), 500)
    }

    return (
        <div>
            <PageHeader
                title="Annotations"
                caption="Here you can add organization- and project-wide annotations. Dashboard-specific ones can be added directly in the dashboard."
                buttons={
                    <LemonButton
                        type="primary"
                        data-attr="create-annotation"
                        data-tooltip="annotations-new-button"
                        onClick={(): void => setOpen(true)}
                    >
                        New annotation
                    </LemonButton>
                }
            />
            <div>
                <LemonTable
                    data-attr="annotations-table"
                    data-tooltip="annotations-table"
                    rowKey="id"
                    rowClassName="cursor-pointer"
                    dataSource={annotations}
                    columns={columns}
                    loading={annotationsLoading}
                    onRow={(annotation): HTMLAttributes<HTMLElement> => ({
                        onClick: (): void => {
                            setSelected(annotation)
                            setOpen(true)
                        },
                    })}
                    emptyState="No annotations yet"
                />
                <div className="flex flex-row justify-center mt-8">
                    {next && (
                        <LemonButton
                            type="primary"
                            icon={loadingNext ? <Spinner size="sm" /> : null}
                            onClick={(): void => {
                                loadAnnotationsNext()
                            }}
                        >
                            Load more annotations
                        </LemonButton>
                    )}
                </div>
            </div>
            <CreateAnnotationModal
                visible={open}
                onCancel={(): void => {
                    closeModal()
                }}
                onSubmit={async (input, selectedDate, annotationScope: AnnotationScope): Promise<void> => {
                    if (selectedAnnotation && (await selectedAnnotation)) {
                        updateAnnotation(selectedAnnotation.id, input)
                    } else {
                        createGlobalAnnotation(input, selectedDate.format('YYYY-MM-DD'), undefined, annotationScope)
                    }
                    closeModal()
                }}
                onDelete={(): void => {
                    if (selectedAnnotation) {
                        deleteAnnotation(selectedAnnotation.id)
                    }
                    closeModal()
                }}
                onRestore={(): void => {
                    if (selectedAnnotation) {
                        restoreAnnotation(selectedAnnotation.id)
                    }
                    closeModal()
                }}
                annotation={selectedAnnotation}
            />
        </div>
    )
}

interface CreateAnnotationModalProps {
    visible: boolean
    onCancel: () => void
    onDelete: () => void
    onRestore: () => void
    onSubmit: (input: string, date: dayjs.Dayjs, annotationScope: AnnotationScope) => void
    annotation?: any
}

enum ModalMode {
    CREATE,
    EDIT,
}

function CreateAnnotationModal(props: CreateAnnotationModalProps): JSX.Element {
    const [scope, setScope] = useState<AnnotationScope.Project | AnnotationScope.Organization>(AnnotationScope.Project)
    const [textInput, setTextInput] = useState('')
    const [modalMode, setModalMode] = useState<ModalMode>(ModalMode.CREATE)
    const [selectedDate, setDate] = useState<dayjs.Dayjs>(dayjs())

    useEffect(() => {
        if (props.annotation) {
            setModalMode(ModalMode.EDIT)
            setTextInput(props.annotation.content)
        } else {
            setModalMode(ModalMode.CREATE)
            setTextInput('')
        }
    }, [props.annotation])

    const _onSubmit = (input: string, date: dayjs.Dayjs, annotationScope: AnnotationScope): void => {
        props.onSubmit(input, date, annotationScope)
        // Reset input
        setTextInput('')
        setDate(dayjs())
        setScope(AnnotationScope.Project)
    }

    return (
        <LemonModal
            isOpen={props.visible}
            footer={
                <>
                    {modalMode === ModalMode.EDIT ? (
                        <div className="flex-1">
                            {!props.annotation?.deleted ? (
                                <LemonButton
                                    type="secondary"
                                    status="danger"
                                    onClick={props.onDelete}
                                    data-attr="delete-annotation"
                                >
                                    Delete annotation
                                </LemonButton>
                            ) : (
                                <LemonButton
                                    type="secondary"
                                    status="primary-alt"
                                    onClick={props.onRestore}
                                    data-attr="restore-annotation"
                                >
                                    Restore annotation
                                </LemonButton>
                            )}
                        </div>
                    ) : null}
                    <LemonButton
                        key="create-annotation-cancel"
                        type={'secondary'}
                        onClick={(): void => props.onCancel()}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        key="create-annotation-submit"
                        data-attr="create-annotation-submit"
                        onClick={(): void => {
                            _onSubmit(textInput, selectedDate, scope)
                        }}
                    >
                        {modalMode === ModalMode.CREATE ? 'Submit' : 'Update'}
                    </LemonButton>
                </>
            }
            onClose={props.onCancel}
            title={modalMode === ModalMode.CREATE ? 'Create annotation' : 'Edit annotation'}
        >
            {modalMode === ModalMode.CREATE ? (
                <span>
                    This annotation will appear on all{' '}
                    <div className="inline-flex">
                        <LemonSelect
                            size="small"
                            dropdownMaxContentWidth={true}
                            options={{
                                [AnnotationScope.Project]: { label: 'project' },
                                [AnnotationScope.Organization]: {
                                    label: 'organization',
                                },
                            }}
                            onChange={(scope) => {
                                if (scope) {
                                    setScope(scope)
                                }
                            }}
                            value={scope}
                        />
                    </div>{' '}
                    insights
                </span>
            ) : null}
            {modalMode === ModalMode.CREATE && (
                <div>
                    <div className="my-2 flex flex-row items-center">
                        Date:&nbsp;
                        <DatePicker
                            getPopupContainer={(trigger): HTMLElement => trigger.parentElement as HTMLElement}
                            value={selectedDate}
                            onChange={(date): void => setDate(date as dayjs.Dayjs)}
                            allowClear={false}
                        />
                    </div>
                </div>
            )}
            <div>Annotation text:</div>
            <LemonTextArea
                data-attr="create-annotation-input"
                maxLength={300}
                className="mt-1"
                rows={4}
                value={textInput}
                onChange={setTextInput}
            />
        </LemonModal>
    )
}
