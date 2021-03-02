import React from 'react'
import { manualCohortCreationLogic } from './manualCohortCreationLogic'
import { Drawer } from 'lib/components/Drawer'
import { useValues, useActions } from 'kea'
import { Input, Button, Divider } from 'antd'
import { PersonsTable } from './PersonsTable'
import { DeleteOutlined } from '@ant-design/icons'
import { PersonType } from '~/types'

interface Props {
    visible: boolean
    onClose: () => void
    onSubmit: () => void
}

export function ManualCreateCohortDrawer({ visible, onClose, onSubmit }: Props): JSX.Element {
    const { selectedPeople, cohortName } = useValues(manualCohortCreationLogic)
    const { clearCohort, removeId, setCohortName, saveCohort } = useActions(manualCohortCreationLogic)

    return (
        <Drawer
            title={'New cohort'}
            className="cohorts-drawer"
            onClose={onClose}
            destroyOnClose={false}
            visible={visible}
            width={750}
        >
            <form
                onSubmit={(e): void => {
                    e.preventDefault()
                    saveCohort()
                    clearCohort()
                    onSubmit()
                }}
            >
                <div className="mb">
                    <Input
                        required
                        autoFocus
                        placeholder="Cohort name..."
                        value={cohortName}
                        data-attr="cohort-name"
                        onChange={(e) => setCohortName(e.target.value)}
                    />
                </div>
                <div className="mt">
                    <Button
                        type="primary"
                        htmlType="submit"
                        disabled={false}
                        data-attr="save-cohort"
                        style={{ marginTop: '1rem' }}
                    >
                        Save cohort
                    </Button>
                </div>
            </form>
            <Divider />
            <PersonsTable
                people={selectedPeople}
                moreActions={[
                    {
                        title: 'Actions',
                        render: function RenderActions(_: string, person: PersonType) {
                            return (
                                <Button danger type="link" onClick={() => removeId(person.id)}>
                                    <DeleteOutlined />
                                </Button>
                            )
                        },
                    },
                ]}
            />
        </Drawer>
    )
}
