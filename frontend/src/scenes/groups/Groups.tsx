import { useActions, useValues } from 'kea'
import { Group, PropertyDefinitionType } from '~/types'
import { groupsListLogic } from './groupsListLogic'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { PersonPageHeader } from 'scenes/persons/PersonPageHeader'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable/types'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { SceneExport } from 'scenes/sceneTypes'
import { GroupsIntroduction } from 'scenes/groups/GroupsIntroduction'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { capitalizeFirstLetter } from 'lib/utils'

export const scene: SceneExport = {
    component: Groups,
    logic: groupsListLogic,
    paramsToProps: ({ params: { groupTypeIndex } }) => ({
        groupTypeIndex: parseInt(groupTypeIndex),
    }),
}

export function Groups({ groupTypeIndex }: { groupTypeIndex?: string } = {}): JSX.Element {
    const {
        groupTypeName: { singular, plural },
        groups,
        groupsLoading,
        search,
    } = useValues(groupsListLogic)
    const { loadGroups, setSearch } = useActions(groupsListLogic)
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
                <PersonPageHeader activeGroupTypeIndex={parseInt(groupTypeIndex)} />
                <GroupsIntroduction access={groupsAccessStatus} />
            </>
        )
    }

    const columns: LemonTableColumns<Group> = [
        {
            title: capitalizeFirstLetter(plural),
            key: 'group_key',
            render: function Render(_, group: Group) {
                return (
                    <Link to={urls.group(group.group_type_index.toString(), group.group_key)}>
                        {groupDisplayId(group.group_key, group.group_properties)}
                    </Link>
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
            <PersonPageHeader activeGroupTypeIndex={parseInt(groupTypeIndex)} />
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
