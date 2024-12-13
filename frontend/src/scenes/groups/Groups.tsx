import { useActions, useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { TZLabel } from 'lib/components/TZLabel'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable/types'
import { Link } from 'lib/lemon-ui/Link'
import { capitalizeFirstLetter } from 'lib/utils'
import { GroupsIntroduction } from 'scenes/groups/GroupsIntroduction'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { urls } from 'scenes/urls'

import { Group, PropertyDefinitionType } from '~/types'

import { groupsListLogic } from './groupsListLogic'

export function Groups({ groupTypeIndex }: { groupTypeIndex: number }): JSX.Element {
    const {
        groupTypeName: { singular, plural },
        groups,
        groupsLoading,
        search,
    } = useValues(groupsListLogic({ groupTypeIndex }))
    const { loadGroups, setSearch } = useActions(groupsListLogic({ groupTypeIndex }))
    const { groupsAccessStatus } = useValues(groupsAccessLogic)

    if (groupTypeIndex === undefined) {
        throw new Error('groupTypeIndex is undefined')
    }

    if (
        groupsAccessStatus == GroupsAccessStatus.HasAccess ||
        groupsAccessStatus == GroupsAccessStatus.HasGroupTypes ||
        groupsAccessStatus == GroupsAccessStatus.NoAccess
    ) {
        return (
            <>
                <GroupsIntroduction />
            </>
        )
    }

    const columns: LemonTableColumns<Group> = [
        {
            title: capitalizeFirstLetter(plural),
            key: 'group_key',
            render: function Render(_, group: Group) {
                return (
                    <LemonTableLink
                        to={urls.group(group.group_type_index.toString(), group.group_key)}
                        title={groupDisplayId(group.group_key, group.group_properties)}
                    />
                )
            },
        },
        {
            title: 'First seen',
            key: 'created_at',
            render: function Render(_, group: Group) {
                return <TZLabel time={group.created_at} />
            },
        },
    ]

    return (
        <>
            <LemonInput
                type="search"
                placeholder={`Search for ${plural}`}
                onChange={setSearch}
                value={search}
                data-attr="group-search"
                className="mb-4"
            />
            <LemonDivider className="mb-4" />
            <LemonTable
                columns={columns}
                rowKey="group_key"
                loading={groupsLoading}
                dataSource={groups.results}
                expandable={{
                    expandedRowRender: function RenderPropertiesTable({ group_properties }) {
                        return <PropertiesTable type={PropertyDefinitionType.Group} properties={group_properties} />
                    },
                    rowExpandable: ({ group_properties }) =>
                        !!group_properties && Object.keys(group_properties).length > 0,
                }}
                pagination={{
                    controlled: true,
                    onBackward: groups.previous
                        ? () => {
                              loadGroups(groups.previous)
                              window.scrollTo(0, 0)
                          }
                        : undefined,
                    onForward: groups.next
                        ? () => {
                              loadGroups(groups.next)
                              window.scrollTo(0, 0)
                          }
                        : undefined,
                }}
                emptyState={
                    <>
                        <LemonBanner type="info">
                            No {plural} found. Make sure to send properties with your {singular} for them to show up in
                            the list.{' '}
                            <Link to="https://posthog.com/docs/user-guides/group-analytics" target="_blank">
                                Read more here.
                            </Link>
                        </LemonBanner>
                        <CodeSnippet language={Language.JavaScript} wrap>
                            {`posthog.group('${singular}', 'id:5', {\n` +
                                `    name: 'Awesome ${singular}',\n` +
                                '    value: 11\n' +
                                '});'}
                        </CodeSnippet>
                    </>
                }
            />
        </>
    )
}
