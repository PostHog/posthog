import React from 'react'
import { CohortGroup } from './CohortGroup'
import { cohortLogic } from './cohortLogic'
import { Button, Divider, Input } from 'antd'
import { useValues, useActions } from 'kea'
import { CohortType } from '~/types'
import { Persons } from './Persons'

const isSubmitDisabled = (cohort: CohortType): boolean => {
    if (cohort && cohort.groups) {
        return !cohort.groups.some((group) => Object.keys(group).length)
    }
    return true
}

export function Cohort(props: { onChange: CallableFunction; cohort: CohortType }): JSX.Element {
    const { setCohort, saveCohort } = useActions(cohortLogic(props))
    const { cohort, lastSavedAt } = useValues(cohortLogic(props))

    if (cohort.groups.length == 0) {
        return null
    }
    return (
        <div style={{ maxWidth: 750 }} className="mb">
            <form
                onSubmit={(e): void => {
                    e.preventDefault()
                    saveCohort(cohort)
                }}
            >
                <div className="mb">
                    <Input
                        required
                        autoFocus
                        placeholder="Cohort name..."
                        value={cohort.name}
                        data-attr="cohort-name"
                        onChange={(e) => setCohort({ ...cohort, name: e.target.value })}
                    />
                </div>
                {cohort.groups.map((group, index) => (
                    <React.Fragment key={index}>
                        <CohortGroup
                            group={group}
                            allowRemove={cohort.groups.length > 1}
                            index={index}
                            onRemove={() => {
                                cohort.groups.splice(index, 1)
                                setCohort({ ...cohort })
                            }}
                            onChange={(group: Record<string, any>) => {
                                cohort.groups[index] = group
                                setCohort({ ...cohort })
                            }}
                        />
                        {index < cohort.groups.length - 1 && (
                            <div key={index} className="secondary" style={{ textAlign: 'center', margin: 8 }}>
                                {' '}
                                OR{' '}
                            </div>
                        )}
                    </React.Fragment>
                ))}
                <div className="mt">
                    <Button
                        type="primary"
                        htmlType="submit"
                        disabled={isSubmitDisabled(cohort)}
                        data-attr="save-cohort"
                        style={{ marginTop: '1rem' }}
                    >
                        Save cohort
                    </Button>
                    <Button
                        style={{ marginTop: '1rem', marginLeft: 12 }}
                        onClick={() => setCohort({ ...cohort, groups: [...cohort.groups, {}] })}
                    >
                        New group
                    </Button>
                </div>
            </form>
            <Divider />
            {cohort.id !== 'new' && <Persons cohort={cohort} key={lastSavedAt} />}
        </div>
    )
}
