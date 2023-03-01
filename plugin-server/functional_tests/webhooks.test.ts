import { createServer } from 'http'

import { UUIDT } from '../src/utils/utils'
import { capture, createAction, createOrganization, createTeam, createUser, reloadAction } from './api'

let organizationId: string

beforeAll(async () => {
    organizationId = await createOrganization()
})

test.concurrent(`webhooks: fires slack webhook`, async () => {
    // Create an action with post_to_slack enabled.
    // NOTE: I'm not 100% sure how this works i.e. what all the step
    // configuration means so there's probably a more succinct way to do
    // this.
    let webHookCalledWith: any
    const server = createServer((req, res) => {
        let body = ''
        req.on('data', (chunk) => {
            body += chunk
        })
        req.on('end', () => {
            webHookCalledWith = JSON.parse(body)
            res.writeHead(200, { 'Content-Type': 'text/plain' })
            res.end()
        })
    })

    try {
        await new Promise((resolve) => {
            server.on('listening', resolve)
            server.listen()
        })

        const distinctId = new UUIDT().toString()

        const teamId = await createTeam(organizationId, `http://localhost:${server.address()?.port}`)
        const user = await createUser(teamId, new UUIDT().toString())
        const action = await createAction(
            {
                team_id: teamId,
                name: 'slack',
                description: 'slack',
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                deleted: false,
                post_to_slack: true,
                slack_message_format: 'default',
                created_by_id: user.id,
                is_calculating: false,
                last_calculated_at: new Date().toISOString(),
            },
            [
                {
                    name: 'slack',
                    tag_name: 'div',
                    text: 'text',
                    href: null,
                    url: 'http://localhost:8000',
                    url_matching: null,
                    event: '$autocapture',
                    properties: null,
                    selector: null,
                },
            ]
        )

        await reloadAction(teamId, action.id)

        await capture({
            teamId,
            distinctId,
            uuid: new UUIDT().toString(),
            event: '$autocapture',
            properties: {
                name: 'hehe',
                uuid: new UUIDT().toString(),
                $current_url: 'http://localhost:8000',
                $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: 'text' }],
            },
        })

        for (const _ in Array.from(Array(20).keys())) {
            if (webHookCalledWith) {
                break
            }
            await new Promise((resolve) => setTimeout(resolve, 1000))
        }

        expect(webHookCalledWith).toEqual({ text: 'default' })
    } finally {
        server.close()
    }
})
