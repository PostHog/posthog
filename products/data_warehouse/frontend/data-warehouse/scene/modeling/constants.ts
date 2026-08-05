export const PAGE_SIZE = 25
export const NODE_WIDTH = 180
export const NODE_HEIGHT = 120

// Above this node count, ELK's NETWORK_SIMPLEX node placement (which scales
// super-linearly and runs on the main thread) becomes the dominant cost of
// showing the graph. We switch to the much cheaper BRANDES_KOEPF placement for
// large graphs; smaller graphs keep NETWORK_SIMPLEX for its tighter layout.
export const LARGE_GRAPH_NODE_THRESHOLD = 150

export const TOP_HANDLE_POSITION = {
    x: NODE_WIDTH / 2,
    y: 0,
}

export const BOTTOM_HANDLE_POSITION = {
    x: NODE_WIDTH / 2,
    y: NODE_HEIGHT,
}

export const LEFT_HANDLE_POSITION = {
    x: 0,
    y: NODE_HEIGHT / 2,
}

export const RIGHT_HANDLE_POSITION = {
    x: NODE_WIDTH,
    y: NODE_HEIGHT / 2,
}
