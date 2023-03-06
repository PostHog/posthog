import ClickHouse from '@posthog/clickhouse'

import { defaultConfig } from '../../src/config/config'
import { ClickHouseEvent } from '../../src/types'

export const fetchEvents = async (teamId: number): Promise<ClickHouseEvent[]> => {
    const clickHouseClient = new ClickHouse({
        host: 'localhost',
        dataObjects: true,
        queryOptions: {
            database: defaultConfig.CLICKHOUSE_DATABASE,
            output_format_json_quote_64bit_integers: false,
        },
    })
    const response = await clickHouseClient.querying(`SELECT * FROM events WHERE team_id = ${teamId}`)
    return response.data.map((row) => ({
        ...row,
        properties: JSON.parse(row.properties),
        person_properties: JSON.parse(row.person_properties || 'null'),
        group0_properties: JSON.parse(row.group0_properties || 'null'),
        group1_properties: JSON.parse(row.group1_properties || 'null'),
    })) as unknown as ClickHouseEvent[]
}
