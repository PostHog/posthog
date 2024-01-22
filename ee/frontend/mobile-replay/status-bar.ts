import {NodeType, serializedNodeWithId, wireframe} from "./mobile.types";
import {_isPositiveInteger, STATUS_BAR_ID} from "./transformers";

// in case the status bar is not a fixed height we can guess its height by
// finding the lowest y value in the wireframes that isn't 0
function seekStatusBarHeight(wireframes: wireframe[], startingValue = Infinity): number {
    let statusBarHeight = startingValue;
    wireframes.forEach((wireframe) => {
        if (_isPositiveInteger(wireframe.y) && wireframe.y !== 0 && wireframe.y < statusBarHeight) {
            statusBarHeight = wireframe.y;
        }
        statusBarHeight = seekStatusBarHeight(wireframe.childWireframes || [], statusBarHeight);
    })
    return statusBarHeight;
}

function makeStatusBarStyle(height: number): string {
    const styles: string[] = [
        'position:absolute',
        'top:0',
        'left:0',
        'width:100%',
        'z-index:999999',
        'overflow:hidden',
        'white-space:nowrap',
        'background-color:#000000',
        'color:#ffffff',
        `height:${height}px`,
        'display:flex',
        'align-items:center',
        'justify-content:space-between',
        'flex-direction:row',

    ]
    return styles.join(';')
}

function spacerDiv(idSequence: Generator<number>): serializedNodeWithId {
    const spacerId = idSequence.next().value;
    return {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            'style': 'width: 5px;',
            'data-rrweb-id': spacerId,
        },
        id: spacerId,
        childNodes: [],
    }
}

export function makeStatusBar(wireframes: wireframe[], timestamp: number, idSequence: Generator<number>): serializedNodeWithId {
    const statusBarHeight = seekStatusBarHeight(wireframes)
    const clockId = idSequence.next().value;
    // convert the wireframe timestamp to a date time, then get just the hour and minute of the time from that
    const clockTime = new Date(timestamp).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})
    const clock: serializedNodeWithId = {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            'data-rrweb-id': clockId,
        },
        id: clockId,
        childNodes: [
            {
                type: NodeType.Text,
                textContent: clockTime,
                id: idSequence.next().value,
            },
        ]
    };
    const battery: serializedNodeWithId = {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            'data-rrweb-id': idSequence.next().value,
        },
        id: idSequence.next().value,
        childNodes: [
            {
                type: NodeType.Text,
                textContent: '🔋',
                id: idSequence.next().value,
            },
        ]
    }

    // the left block holds things like the clock and system notifications e.g. usb debugging is active
    const leftBlockId = idSequence.next().value;
    const leftBlock: serializedNodeWithId = {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            style: 'display:flex;flex-direction:row;align-items:center;',
            'data-rrweb-id': leftBlockId,
        },
        id: leftBlockId,
        childNodes: [
            spacerDiv(idSequence),
            clock,
        ]
    }

    // the right block holds things like the battery and wifi status
    const rightBlockId = idSequence.next().value;
    const rightBlock: serializedNodeWithId = {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            style: 'display:flex;flex-direction:row;align-items:center;',
            'data-rrweb-id': rightBlockId,
        },
        id: rightBlockId,
        childNodes: [
            battery,
            spacerDiv(idSequence),
        ]
    }
    return {
        type: NodeType.Element,
        tagName: 'div',
        attributes: {
            style: makeStatusBarStyle(statusBarHeight),
            'data-rrweb-id': STATUS_BAR_ID,
        },
        id: STATUS_BAR_ID,
        childNodes: [
            leftBlock, rightBlock
        ],
    }
}
