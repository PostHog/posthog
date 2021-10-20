import React, { useEffect } from 'react'
import { useValues, useActions } from 'kea'
import { PersonsTable } from './PersonsTable'
import { Button, Row, Radio, Alert } from 'antd'
import { ExportOutlined, PlusOutlined } from '@ant-design/icons'
import { PageHeader } from 'lib/components/PageHeader'
import { personsLogic } from './personsLogic'
import { Link } from 'lib/components/Link'
import { CohortType } from '~/types'
import { LinkButton } from 'lib/components/LinkButton'
import { ClockCircleFilled } from '@ant-design/icons'
import { toParams } from 'lib/utils'
import { PersonsSearch } from './PersonsSearch'
import { IconExternalLink } from 'lib/components/icons'

export function Persons({ cohort }: { cohort: CohortType }): JSX.Element {
    const { loadPersons, setListFilters } = useActions(personsLogic)
    const { persons, listFilters, personsLoading } = useValues(personsLogic)

    useEffect(
        () => {
            if (cohort) {
                setListFilters({ cohort: cohort.id })
                loadPersons()
            }
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        []
    )

    return (
        <div className="persons-list">
            {!cohort && <PageHeader title="Persons" />}
            <Row style={{ gap: '0.75rem' }} className="mb">
                <div style={{ flexGrow: 1, maxWidth: 600 }}>
                    <PersonsSearch autoFocus={!cohort} />
                    <div className="text-muted text-small">
                        You can also filter persons that have a certain property set (e.g. <code>has:email</code> or{' '}
                        <code>has:name</code>)
                    </div>
                </div>
                <div>
                    <Radio.Group
                        buttonStyle="solid"
                        onChange={(e) => {
                            const key = e.target.value
                            setListFilters({ is_identified: key === 'all' ? undefined : key })
                            loadPersons()
                        }}
                        value={listFilters.is_identified !== undefined ? listFilters.is_identified.toString() : 'all'}
                    >
                        <Radio.Button data-attr="people-types-tab-all" value="all">
                            All persons
                        </Radio.Button>
                        <Radio.Button data-attr="people-types-tab-identified" value="true">
                            Identified
                        </Radio.Button>
                        <Radio.Button data-attr="people-types-tab-anonymous" value="false">
                            Unidentified
                        </Radio.Button>
                    </Radio.Group>
                </div>
            </Row>
            {listFilters.is_identified === 'false' && (
                <div className="mb">
                    {/* TODO: Product suggestion: We'll want to turn these off for advanced users  */}
                    <Alert
                        type="info"
                        closable
                        message={
                            <>
                                Unidentified persons are usually anonymous visitors to your app or website that have not
                                been identified to you. To mark a person as identified, call{' '}
                                <code>posthog.identify</code> on your frontend.{' '}
                                <a
                                    href="https://posthog.com/docs/integrations/js-integration?utm_medium=in-product&utm_campaign=persons-unidentified#identifying-users"
                                    target="_blank"
                                    style={{ display: 'inline-flex', alignItems: 'center' }}
                                >
                                    <IconExternalLink /> Learn more
                                </a>
                            </>
                        }
                        showIcon
                    />
                </div>
            )}
            <div className="mb text-right">
                {cohort ? (
                    <LinkButton
                        to={`/sessions?${toParams({ properties: [{ key: 'id', value: cohort.id, type: 'cohort' }] })}`}
                        target="_blank"
                    >
                        <ClockCircleFilled /> View sessions
                    </LinkButton>
                ) : null}
                <Button
                    type="default"
                    icon={<ExportOutlined />}
                    href={'/api/person.csv' + (listFilters.cohort ? '?cohort=' + listFilters.cohort : '')}
                    style={{ marginLeft: 8 }}
                >
                    Export
                </Button>
                {/* TODO: Hidden until new cohorts UX is defined */}
                <Link to="/cohorts/new" style={{ display: 'none' }} className="ml">
                    <Button type="default" icon={<PlusOutlined />}>
                        New Cohort
                    </Button>
                </Link>
            </div>

            <div>
                <PersonsTable
                    people={persons.results}
                    loading={personsLoading}
                    hasPrevious={!!persons.previous}
                    hasNext={!!persons.next}
                    loadPrevious={() => loadPersons(persons.previous)}
                    loadNext={() => loadPersons(persons.next)}
                    allColumns
                    backTo={cohort ? 'Cohort' : 'Persons'}
                />
            </div>
        </div>
    )
}
