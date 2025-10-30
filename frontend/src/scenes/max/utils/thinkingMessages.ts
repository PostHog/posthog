import { inStorybookTestRunner } from 'lib/utils'

import { AssistantMessage } from '~/queries/schema/schema-assistant-messages'

export const THINKING_MESSAGES = [
    'Booping', // playful interaction
    'Crunching', // data in progress
    'Digging', // going deep
    'Fetching', // retrieving something
    'Inferring', // making sense of things
    'Indexing', // organizing info
    'Juggling', // handling multiple things
    'Noodling', // casual problem-solving
    'Peeking', // quick look
    'Percolating', // slow thinking
    'Poking', // testing ideas
    'Pondering', // thoughtful pause
    'Scanning', // fast overview
    'Scrambling', // chaotic progress
    'Sifting', // sorting signal from noise
    'Sniffing', // searching with instinct
    'Spelunking', // deep exploration
    'Tinkering', // tweaking stuff
    'Unraveling', // breaking things down
    'Decoding', // translating complexity
    'Trekking', // on a journey
    'Sorting', // putting things in order
    'Trimming', // cleaning things up
    'Mulling', // slow consideration
    'Surfacing', // bringing something up
    'Rummaging', // messy searching
    'Scouting', // looking ahead
    'Scouring', // intense searching
    'Threading', // connecting things
    'Hunting', // focused seeking
    'Swizzling', // techy weirdness
    'Grokking', // deep understanding
    'Hedging', // hedgehog pun
    'Scheming', // clever planning
    'Unfurling', // opening up ideas
    'Puzzling', // solving something tricky
    'Dissecting', // breaking it apart
    'Stacking', // building layers
    'Snuffling', // hedgehog behavior
    'Hashing', // working something out
    'Clustering', // grouping related things
    'Teasing', // nudging out meaning
    'Cranking', // pushing through work
    'Merging', // putting ideas together
    'Snooping', // poking around data
    'Rewiring', // making new connections
    'Bundling', // grouping ideas
    'Linking', // making a connection
    'Mapping', // plotting points
    'Tickling', // triggering results lightly
    'Flicking', // small, quick action
    'Hopping', // fast, light progress
    'Rolling', // forward movement
    'Zipping', // fast execution
    'Twisting', // shifting structure
    'Blooming', // ideas forming
    'Sparking', // fresh thought forming
    'Nesting', // organizing structure
    'Looping', // revisiting paths
    'Wiring', // making connections
    'Snipping', // precise cutting
    'Zoning', // deep focus
    'Tracing', // following logic
    'Warping', // reshaping view
    'Twinkling', // flicker of insight
    'Flipping', // shifting state
    'Priming', // getting ready
    'Snagging', // quick retrieval
    'Scuttling', // fast, scurrying motion
    'Framing', // contextualizing view
    'Sharpening', // refining details
    'Flibbertigibbeting', // flustered but active chaos
    'Kerfuffling', // low-stakes commotion
    'Dithering', // indecisive processing
    'Discombobulating', // intentionally confused
    'Rambling', // aimless but possibly insightful
    'Befuddling', // trying to untangle confusion
    'Waffling', // bouncing between options
    'Muckling', // clinging onto something
    'Hobnobbing', // talking to the data gods
    'Galumphing', // awkward progress
    'Puttering', // low-energy thinking
    'Whiffling', // light, directionless searching
    'Thinking', // just thinking, like in the old days
]

export const getRandomThinkingMessage = (): string => {
    if (inStorybookTestRunner()) {
        return 'Thinking...'
    }
    const randomIndex = Math.floor(Math.random() * THINKING_MESSAGES.length)
    return THINKING_MESSAGES[randomIndex] + '...'
}

interface ServerToolUseBlock {
    type: 'server_tool_use'
    name: string
    input: Record<string, unknown>
    id: string
    results?: { title: string; url: string }[]
}

interface ThinkingBlock {
    type: 'thinking'
    thinking: string
}

export const getThinkingMessageFromResponse = (message: AssistantMessage): (ServerToolUseBlock | ThinkingBlock)[] => {
    const thinkingMeta = message.meta?.thinking
    if (!thinkingMeta) {
        return []
    }
    const blocks: (ServerToolUseBlock | ThinkingBlock)[] = []
    const toolUseIdToBlock: Record<string, ServerToolUseBlock> = {}
    for (const block of thinkingMeta) {
        if (block.type === 'thinking') {
            blocks.push({ type: 'thinking', thinking: block.thinking as string })
        } else if (block.type === 'server_tool_use') {
            toolUseIdToBlock[block.id as string] = {
                id: block.id as string,
                type: 'server_tool_use',
                name: block.name as string,
                input: block.input as Record<string, unknown>,
            }
            blocks.push(toolUseIdToBlock[block.id as string])
        } else if (block.type === 'web_search_tool_result') {
            if (!Array.isArray(block.content)) {
                console.error('web_search_tool_result is not an array', block)
                continue // Making TypeScript happy
            }
            toolUseIdToBlock[block.tool_use_id as string].results = block.content.map((content) => ({
                title: content.title as string,
                url: content.url as string,
            }))
        } else if (block.type === 'reasoning') {
            // OpenAI
            blocks.push({ type: 'thinking', thinking: (block.summary as any[])[0].text as string })
        }
    }
    return blocks
}
