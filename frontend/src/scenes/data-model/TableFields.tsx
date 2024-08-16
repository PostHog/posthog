import { LemonTable } from "@posthog/lemon-ui";

const FAKE_DATA = [
    { column: 'id', type: 'integer' },
    { column: 'name', type: 'string' },
    { column: 'email', type: 'string' },
    { column: 'created_at', type: 'datetime' },
    { column: 'is_active', type: 'boolean' },
    { column: 'properties', type: 'json' },
]

const FAKE_JOINED_DATA = [
    { name: "customer_email", type: "string", table: "prod_stripe_invoice" },
    { name: "account_size", type: "string", table: "prod_stripe_invoice" },
]

export function TableFields(): JSX.Element {


    return <div className="">
        <div>
            <div className="pl-4 mt-4">
                <h3>person</h3>
            </div>
        </div>
        <div className="flex flex-col gap-1">
            <div className="pl-4 mt-4">
                <h4>Schema</h4>
            </div>
            <LemonTable
                className="bg-[white] rounded-none"
                columns={[
                    {
                        key: 'column',
                        render: (_, { column }) => column
                    },
                    {
                        key: 'type',
                        render: (_, { type }) => type
                    },
                ]}
                dataSource={FAKE_DATA}
                loading={false}
                showHeader={false}
            />
        </div>
        <div>
            <div className="pl-4 mt-4">
                <h4>Joined Tables</h4>
            </div>
            <LemonTable
                className="bg-[white] rounded-none"
                columns={[
                    {
                        key: 'name',
                        render: (_, { name, table }) => (
                            <div className="flex flex-col">
                                <span className="font-bold">{name}</span>
                                <span className="text-muted">{table}</span>
                            </div>
                        )
                    },
                    {
                        key: 'type',
                        render: (_, { type }) => type
                    },
                ]}
                dataSource={FAKE_JOINED_DATA}
                loading={false}
                showHeader={false}
            />
        </div>
    </div>
}