import { inStorybookTestRunner } from 'lib/utils'

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
        return 'Thinking'
    }
    const randomIndex = Math.floor(Math.random() * THINKING_MESSAGES.length)
    return THINKING_MESSAGES[randomIndex]
}
