import { createServer } from 'http'
import { DateTime } from 'luxon'

import { UUIDT } from '../src/utils/utils'
import { capture, createAction, createHook, createOrganization, createTeam, createUser, reloadAction } from './api'

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

        const organizationId = await createOrganization()
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
                slack_message_format:
                    '[event.name] with [event.properties.name] was triggered by [person.properties.email]',
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
                $set: { email: 't@t.com' },
            },
        })

        for (const _ in Array.from(Array(20).keys())) {
            if (webHookCalledWith) {
                break
            }
            await new Promise((resolve) => setTimeout(resolve, 1000))
        }

        expect(webHookCalledWith).toEqual({ text: `$autocapture with hehe was triggered by t@t.com` })
    } finally {
        server.close()
    }
})

test.concurrent(`webhooks: fires zapier REST webhook`, async () => {
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
        const ts = new Date()

        const organizationId = await createOrganization({ available_features: '{zapier}' })
        const teamId = await createTeam(organizationId, `http://localhost:${server.address()?.port}`)
        const user = await createUser(teamId, new UUIDT().toString())
        const action = await createAction(
            {
                team_id: teamId,
                name: 'zapier',
                description: 'zapier',
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                deleted: false,
                post_to_slack: false,
                slack_message_format:
                    '[event.name] with [event.properties.name] was triggered by [person.properties.email]',
                created_by_id: user.id,
                is_calculating: false,
                last_calculated_at: new Date().toISOString(),
            },
            [
                {
                    name: 'zapier',
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
        await createHook(teamId, user.id, action.id, `http://localhost:${server.address()?.port}`)

        await reloadAction(teamId, action.id)

        const eventUuid = new UUIDT().toString()
        await capture({
            teamId,
            distinctId,
            uuid: eventUuid,
            event: '$autocapture',
            properties: {
                name: 'hehe',
                uuid: new UUIDT().toString(),
                $current_url: 'http://localhost:8000',
                $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: 'text' }],
                $set: { email: 't@t.com' },
            },
            eventTime: ts,
            sentAt: undefined,
        })

        for (const _ in Array.from(Array(20).keys())) {
            if (webHookCalledWith) {
                break
            }
            await new Promise((resolve) => setTimeout(resolve, 1000))
        }

        const expectedData = {
            distinctId: distinctId,
            elementsList: [
                {
                    $el_text: 'text',
                    attributes: {},
                    nth_child: 1,
                    nth_of_type: 2,
                    order: 0,
                    tag_name: 'div',
                    text: 'text',
                },
            ],
            event: '$autocapture',
            eventUuid: eventUuid,
            person: {
                created_at: new Date(DateTime.fromJSDate(ts).toFormat('yyyy-MM-dd HH:mm:ss')).toISOString(),
                properties: {
                    $creator_event_uuid: eventUuid,
                    $initial_current_url: 'http://localhost:8000',
                    $current_url: 'http://localhost:8000',
                    email: 't@t.com',
                },
                uuid: expect.any(String),
            },
            properties: {
                $current_url: 'http://localhost:8000',
                $sent_at: expect.any(String),
                $set: {
                    email: 't@t.com',
                    $current_url: 'http://localhost:8000',
                },
                $set_once: {
                    $initial_current_url: 'http://localhost:8000',
                },
                name: 'hehe',
                uuid: eventUuid,
            },
            teamId: teamId,
            timestamp: ts.toISOString(),
        }

        expect(webHookCalledWith).toEqual(expect.objectContaining({ data: expectedData }))
    } finally {
        server.close()
    }
})
