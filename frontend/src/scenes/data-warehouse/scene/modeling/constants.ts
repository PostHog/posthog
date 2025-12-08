export const NODE_WIDTH = 180
export const NODE_HEIGHT = 50

export const NODE_GAP = 60

// Minimum horizontal distance between parallel edges
export const MINIMUM_EDGE_SPACING = 200

// NODE_EDGE_GAP is MINIMUM_EDGE_SPACING - 1 to account for the 1px stroke width of edges
export const NODE_EDGE_GAP = MINIMUM_EDGE_SPACING - 1
export const NODE_LAYER_GAP = NODE_GAP * 1.5

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
