import { LemonButton } from "@posthog/lemon-ui"
import { useActions } from "kea"
import { LemonTable, LemonTableColumns } from "lib/components/LemonTable"
import { CreateRoleModal } from "./CreateRoleModal"
import { rolesLogic } from "./rolesLogic"


export function Roles(): JSX.Element {
    const { setCreateRoleModalShown } = useActions(rolesLogic)

    const columns: LemonTableColumns<{}> = [
        {
            key: 'role',
            title: 'Role',
            render: function RoleRender(_, role) {
                return <></>
            },
        },
    ]

    return (
        <>
            <h2 id="roles" className="subtitle" style={{ justifyContent: 'space-between' }}>
                Roles
                <LemonButton type="primary" onClick={() => setCreateRoleModalShown(true)} data-attr="create-role-button">
                    Create Role
                </LemonButton>
            </h2>
            <LemonTable
                dataSource={[]}
                columns={columns}
                rowKey={() => "id"}
                style={{ marginTop: '1rem' }}
                loading={false}
                data-attr="org-roles-table"
                defaultSorting={{ columnKey: 'level', order: -1 }}
                pagination={{ pageSize: 50 }}
            />
            <CreateRoleModal />
        </>
    )
}
