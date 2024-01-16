import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { TZLabel } from 'lib/components/TZLabel'
import { IconDelete } from 'lib/lemon-ui/icons'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { PersonDeleteModal } from 'scenes/persons/PersonDeleteModal'
import { personDeleteModalLogic } from 'scenes/persons/personDeleteModalLogic'
import { personsLogic } from 'scenes/persons/personsLogic'

import { PersonType, PropertyDefinitionType } from '~/types'

import { PersonDisplay } from './PersonDisplay'

interface PersonsTableType {
    people: PersonType[]
    loading?: boolean
    hasPrevious?: boolean
    hasNext?: boolean
    loadPrevious?: () => void
    loadNext?: () => void
    compact?: boolean
    extraColumns?: LemonTableColumns<PersonType>
    emptyState?: JSX.Element
}

export function PersonsTable({
    people,
    loading = false,
    hasPrevious,
    hasNext,
    loadPrevious,
    loadNext,
    compact,
    extraColumns,
    emptyState,
}: PersonsTableType): JSX.Element {
    const { showPersonDeleteModal } = useActions(personDeleteModalLogic)
    const { loadPersons } = useActions(personsLogic)

    const columns: LemonTableColumns<PersonType> = [
        {
            title: 'Person',
            key: 'person',
            render: function Render(_, person: PersonType) {
                return <PersonDisplay withIcon person={person} />
            },
        },
        ...(!compact
            ? ([
                  {
                      title: 'ID',
                      key: 'id',
                      render: function Render(_, person: PersonType) {
                          return (
                              <div className="overflow-hidden">
                                  {person.distinct_ids.length && (
                                      <CopyToClipboardInline
                                          explicitValue={person.distinct_ids[0]}
                                          iconStyle={{ color: 'var(--primary)' }}
                                          description="person distinct ID"
                                      >
                                          {person.distinct_ids[0]}
                                      </CopyToClipboardInline>
                                  )}
                              </div>
                          )
                      },
                  },
                  {
                      title: 'First seen',
                      dataIndex: 'created_at',
                      render: function Render(created_at: PersonType['created_at']) {
                          return created_at ? <TZLabel time={created_at} /> : <></>
                      },
                  },
                  {
                      render: function Render(_, person: PersonType) {
                          return (
                              <LemonButton
                                  onClick={() => showPersonDeleteModal(person, () => loadPersons())}
                                  icon={<IconDelete />}
                                  status="danger"
                                  size="small"
                              />
                          )
                      },
                  },
              ] as Array<LemonTableColumn<PersonType, keyof PersonType | undefined>>)
            : []),
        ...(extraColumns || []),
    ]

    return (
        <>
            <LemonTable
                data-attr="persons-table"
                columns={columns}
                loading={loading}
                rowKey="id"
                pagination={{
                    controlled: true,
                    pageSize: 100, // From `posthog/api/person.py`
                    onForward: hasNext
                        ? () => {
                              loadNext?.()
                              window.scrollTo(0, 0)
                          }
                        : undefined,
                    onBackward: hasPrevious
                        ? () => {
                              loadPrevious?.()
                              window.scrollTo(0, 0)
                          }
                        : undefined,
                }}
                expandable={{
                    expandedRowRender: function RenderPropertiesTable({ properties }) {
                        return Object.keys(properties).length ? (
                            <PropertiesTable type={PropertyDefinitionType.Person} properties={properties} />
                        ) : (
                            'This person has no properties.'
                        )
                    },
                }}
                dataSource={people}
                emptyState={emptyState ? emptyState : 'No persons'}
                nouns={['person', 'persons']}
            />
            <PersonDeleteModal />
        </>
    )
}
