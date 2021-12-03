import React, { useState, useEffect, HTMLAttributes } from 'react'
import { useValues, useActions } from 'kea'
import { Tag, Button, Modal, Input, Row, Menu, Dropdown } from 'antd'
import { annotationsModel } from '~/models/annotationsModel'
import { annotationsTableLogic } from './logic'
import { DeleteOutlined, RedoOutlined, ProjectOutlined, DeploymentUnitOutlined, DownOutlined } from '@ant-design/icons'
import { annotationScopeToName } from 'lib/constants'
import { PageHeader } from 'lib/components/PageHeader'
import { PlusOutlined } from '@ant-design/icons'
import { AnnotationType, AnnotationScope } from '~/types'
import dayjsGenerateConfig from 'rc-picker/lib/generate/dayjs'
import generatePicker from 'antd/lib/date-picker/generatePicker'
import { SceneExport } from 'scenes/sceneTypes'
import { dayjs } from 'lib/dayjs'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { LemonTable, LemonTableColumns, LemonTableColumn } from 'lib/components/LemonTable'
import { createdByColumn } from 'lib/components/LemonTable/columnUtils'
import { TZLabel } from 'lib/components/TimezoneAware'

const DatePicker = generatePicker<dayjs.Dayjs>(dayjsGenerateConfig)

const { TextArea } = Input

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
                return (
                    <div
                        className="ph-no-capture"
                        style={{
                            width: 'auto',
                            maxWidth: 250,
                        }}
                    >
                        {annotation.content}
                    </div>
                )
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
                return annotation.deleted ? <Tag color="red">Deleted</Tag> : <Tag color="green">Active</Tag>
            },
        },
        {
            title: 'Scope',
            render: function RenderType(_, annotation: AnnotationType): JSX.Element {
                return annotation.scope === AnnotationScope.DashboardItem ? (
                    <Tag color="blue">Insight</Tag>
                ) : annotation.scope === AnnotationScope.Project ? (
                    <Tag color="purple">Project</Tag>
                ) : annotation.scope === AnnotationScope.Organization ? (
                    <Tag color="pink">Organization</Tag>
                ) : (
                    <Tag>Unknown ({annotation.scope})</Tag>
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
                    <Button
                        type="primary"
                        data-attr="create-annotation"
                        onClick={(): void => setOpen(true)}
                        icon={<PlusOutlined />}
                    >
                        New Annotation
                    </Button>
                }
            />
            <div>
                <LemonTable
                    data-attr="annotations-table"
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
                <div
                    style={{
                        visibility: next ? 'visible' : 'hidden',
                        margin: '2rem auto 5rem',
                        textAlign: 'center',
                    }}
                >
                    {loadingNext ? (
                        <Spinner size="sm" />
                    ) : (
                        <Button
                            type="primary"
                            onClick={(): void => {
                                loadAnnotationsNext()
                            }}
                        >
                            Load more annotations
                        </Button>
                    )}
                </div>
            </div>
            <CreateAnnotationModal
                visible={open}
                onCancel={(): void => {
                    closeModal()
                }}
                onSubmit={async (input, selectedDate): Promise<void> => {
                    if (selectedAnnotation && (await selectedAnnotation)) {
                        updateAnnotation(selectedAnnotation.id, input)
                    } else {
                        createGlobalAnnotation(input, selectedDate.format('YYYY-MM-DD'))
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
    onSubmit: (input: string, date: dayjs.Dayjs) => void
    annotation?: any
}

enum ModalMode {
    CREATE,
    EDIT,
}

function CreateAnnotationModal(props: CreateAnnotationModalProps): JSX.Element {
    const [scope, setScope] = useState<AnnotationScope>(AnnotationScope.Project)
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

    const _onSubmit = (input: string, date: dayjs.Dayjs): void => {
        props.onSubmit(input, date)
        // Reset input
        setTextInput('')
        setDate(dayjs())
        setScope(AnnotationScope.Project)
    }

    return (
        <Modal
            footer={[
                <Button key="create-annotation-cancel" onClick={(): void => props.onCancel()}>
                    Cancel
                </Button>,
                <Button
                    type="primary"
                    key="create-annotation-submit"
                    data-attr="create-annotation-submit"
                    onClick={(): void => {
                        _onSubmit(textInput, selectedDate)
                    }}
                >
                    {modalMode === ModalMode.CREATE ? 'Submit' : 'Update'}
                </Button>,
            ]}
            closable={false}
            visible={props.visible}
            onCancel={props.onCancel}
            title={modalMode === ModalMode.CREATE ? 'Create annotation' : 'Edit ennotation'}
        >
            {modalMode === ModalMode.CREATE ? (
                <span>
                    This annotation will appear on all
                    <Dropdown
                        overlay={
                            <Menu activeKey={scope} onSelect={(e) => setScope(e.key as AnnotationScope)}>
                                <Menu.Item key={AnnotationScope.Project} icon={<ProjectOutlined />}>
                                    Project
                                </Menu.Item>
                                <Menu.Item key={AnnotationScope.Organization} icon={<DeploymentUnitOutlined />}>
                                    Organization
                                </Menu.Item>
                            </Menu>
                        }
                    >
                        <Button style={{ marginLeft: 8, marginRight: 8 }}>
                            {annotationScopeToName.get(scope)} <DownOutlined />
                        </Button>
                    </Dropdown>{' '}
                    charts
                </span>
            ) : (
                <Row justify="space-between">
                    <span>Change existing annotation text</span>
                    {!props.annotation?.deleted ? (
                        <DeleteOutlined
                            className="text-danger"
                            onClick={(): void => {
                                props.onDelete()
                            }}
                        />
                    ) : (
                        <RedoOutlined
                            className="button-border clickable"
                            onClick={(): void => {
                                props.onRestore()
                            }}
                        />
                    )}
                </Row>
            )}
            <br />
            {modalMode === ModalMode.CREATE && (
                <div>
                    Date:
                    <DatePicker
                        style={{ marginTop: 16, marginLeft: 8, marginBottom: 16 }}
                        getPopupContainer={(trigger): HTMLElement => trigger.parentElement as HTMLElement}
                        value={selectedDate}
                        onChange={(date): void => setDate(date as dayjs.Dayjs)}
                        allowClear={false}
                    />
                </div>
            )}
            <TextArea
                data-attr="create-annotation-input"
                maxLength={300}
                style={{ marginBottom: 12, marginTop: 5 }}
                rows={4}
                value={textInput}
                onChange={(e): void => setTextInput(e.target.value)}
            />
        </Modal>
    )
}
