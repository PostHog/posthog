import api, { ApiRequest } from 'lib/api'

import type { ChatChannel, ChatChannelMember } from './types'

class ConversationsChannelsApiRequest extends ApiRequest {
    channels(): ApiRequest {
        return this.projectsDetail().addPathComponent('conversations').addPathComponent('channels')
    }

    channel(id: string): ApiRequest {
        return this.channels().addPathComponent(id)
    }
}

function request(): ConversationsChannelsApiRequest {
    return new ConversationsChannelsApiRequest()
}

export const channelsApi = {
    async list(): Promise<ChatChannel[]> {
        const response = await request().channels().get()
        return response.results ?? response
    },

    async get(channelId: string): Promise<ChatChannel> {
        return await request().channel(channelId).get()
    },

    async create(data: { name: string; description?: string }): Promise<ChatChannel> {
        return await request().channels().create({ data })
    },

    async update(channelId: string, data: Partial<{ name: string; description: string }>): Promise<ChatChannel> {
        return await request().channel(channelId).update({ data })
    },

    async delete(channelId: string): Promise<void> {
        return await request().channel(channelId).delete()
    },

    async join(channelId: string): Promise<ChatChannel> {
        return await request().channel(channelId).withAction('join').create({ data: {} })
    },

    async leave(channelId: string): Promise<ChatChannel> {
        return await request().channel(channelId).withAction('leave').create({ data: {} })
    },

    async members(channelId: string): Promise<ChatChannelMember[]> {
        const response = await request().channel(channelId).withAction('members').get()
        return response.results ?? response
    },
}

export { api }
