import { useRef, useEffect, useState } from 'react';
import { TableFields } from './TableFields';
import IconStripe from 'public/services/stripe.png'

interface Position {
    x: number
    y: number
}

interface NodePosition {
    node: React.FC
    position: Position
}

const NODES: NodePosition[] = [
    {
        node: TableFieldNode,
        position: { x: 1000, y: 100 },
    },
    {
        node: PostHogNode,
        position: { x: 400, y: 200 },
    },
    {
        node: StripeNode,
        position: { x: 400, y: 400 },
    },
    {
        node: StripeInvoiceNode,
        position: { x: 700, y: 400 },
    },
    {
        node: StripeCustomerNode,
        position: { x: 700, y: 500 },
    }
]

const EDGES =  [
    {
        from: {
            x: 500,
            y: 225
        },
        to: {
            x: 1000,
            y: 225
        }
    },
    {
        from: {
            x: 500,
            y: 425
        },
        to: {
            x: 700,
            y: 425
        }
    },
    {
        from: {
            x: 675,
            y: 425
        },
        to: {
            x: 675,
            y: 525
        }
    },
    {
        from: {
            x: 675,
            y: 525
        },
        to: {
            x: 700,
            y: 525
        }
    }
]

const ScrollableDraggableCanvas = ({ }) => {
    const canvasRef = useRef(null)
    const [isDragging, setIsDragging] = useState(false)
    const [offset, setOffset] = useState({ x: 0, y: 0 })
    const [dragStart, setDragStart] = useState({ x: 0, y: 0 })

    const drawGrid = (ctx, canvasWidth, canvasHeight) => {
        ctx.fillStyle = '#000000'
        const dotSize = 1
        const spacing = 20

        for (let x = offset.x % spacing; x < canvasWidth; x += spacing) {
            for (let y = offset.y % spacing; y < canvasHeight; y += spacing) {
                ctx.fillRect(x, y, dotSize, dotSize)
            }
        }

        EDGES.forEach(({ from, to }) => {
            ctx.beginPath()
            ctx.moveTo(from.x + offset.x, from.y + offset.y)
            ctx.lineTo(to.x + offset.x, to.y + offset.y)
            ctx.strokeStyle = 'black'
            ctx.lineWidth = 1
            ctx.stroke()
        })
    };

    useEffect(() => {
        const canvas = canvasRef.current
        const ctx = canvas.getContext('2d')
        const { width, height } = canvas.getBoundingClientRect()

        canvas.width = width
        canvas.height = height

        drawGrid(ctx, width, height)
    }, [offset]);

    const handleMouseDown = (e) => {
        setIsDragging(true)
        setDragStart({ x: e.clientX - offset.x, y: e.clientY - offset.y })
    };

    const handleMouseMove = (e) => {
        if (!isDragging) return
        const newOffset = {
            x: e.clientX - dragStart.x,
            y: e.clientY - dragStart.y
        };
        setOffset(newOffset)
    };

    const handleMouseUp = () => {
        setIsDragging(false)
    };


    return (
        <div style={{ position: 'relative', width: '100%', height: '95vh', }}>
            <canvas
                ref={canvasRef}
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
                onMouseLeave={handleMouseUp}
                style={{
                    width: '100%',
                    height: '100%',
                    cursor: isDragging ? 'grabbing' : 'grab'
                }}
            />
            {
                NODES.map(({ node: Node, position }) => {
                    return (
                        <div style={{
                            position: 'absolute',
                            left: `${position.x + offset.x}px`,
                            top: `${position.y + offset.y}px`,
                        }}>
                            <Node />
                        </div>
                    )
                })
            }
        </div>
    );
};

export default ScrollableDraggableCanvas;

function StripeNode() {
    return (
        <div className='w-[100px] h-[50px] flex justify-center items-center space-between gap-1' style={{
            background: 'rgba(255, 255, 255, 0.8)',
            border: '1px solid #000',
            borderRadius: '5px',
        }}>

            <img src={IconStripe} alt={'stripe'} height={30} width={30} className="rounded" />
            <span>Stripe</span>
        </div>
    )
}

function StripeInvoiceNode() {
    return (
        <div className='w-[120px] h-[50px] flex justify-center items-center space-between gap-1' style={{
            background: 'rgba(255, 255, 255, 0.8)',
            border: '1px solid #000',
            borderRadius: '5px',
        }}>

            <span>Stripe invoice</span>
        </div>
    )
}

function StripeCustomerNode() {
    return (
        <div className='w-[120px] h-[50px] flex justify-center items-center space-between gap-1' style={{
            background: 'rgba(255, 255, 255, 0.8)',
            border: '1px solid #000',
            borderRadius: '5px',
        }}>

            <span>Stripe customer</span>
        </div>
    )
}

function PostHogNode() {
    return (
        <div className='w-[100px] h-[50px] flex justify-center items-center' style={{
            background: 'rgba(255, 255, 255, 0.8)',
            border: '1px solid #000',
            borderRadius: '5px',
        }}>

            PostHog
        </div>
    )
}

function TableFieldNode() {
    return (
        <div className='w-[500px] h-[600px]' style={{
            background: 'rgba(255, 255, 255, 0.8)',
            border: '1px solid #000',
            borderRadius: '5px',
        }}>

            <TableFields />
        </div>
    )
}