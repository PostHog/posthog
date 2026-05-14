import { useEffect, useRef } from 'react'

interface StarfieldProps {
    speed?: number
    quantity?: number
    starColor?: string
    bgColor?: string
}

export function Starfield({
    speed = 0.5,
    quantity = 300,
    starColor = 'rgba(255,255,255,1)',
    bgColor = 'rgba(0,0,0,1)',
}: StarfieldProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)

    useEffect(() => {
        const canvas = canvasRef.current
        if (!canvas) {
            return
        }
        const parent = canvas.parentElement
        if (!parent) {
            return
        }

        const ctx = canvas.getContext('2d')
        if (!ctx) {
            return
        }

        let w = parent.clientWidth
        let h = parent.clientHeight
        canvas.width = w
        canvas.height = h

        let cx = w / 2
        let cy = h / 2
        let z = (w + h) / 2
        const ratio = quantity / 2

        // Each star: [x, y, z, screenX, screenY, prevScreenX, prevScreenY, visible]
        let stars: number[][] = Array.from({ length: quantity }, () => [
            Math.random() * w * 2 - cx * 2,
            Math.random() * h * 2 - cy * 2,
            Math.round(Math.random() * z),
            0,
            0,
            0,
            0,
            1,
        ])

        let animFrame: number

        const animate = (): void => {
            // Resize check
            const newW = parent.clientWidth
            const newH = parent.clientHeight
            if (newW !== w || newH !== h) {
                w = newW
                h = newH
                canvas.width = w
                canvas.height = h
                cx = w / 2
                cy = h / 2
                z = (w + h) / 2
            }

            // Update stars
            for (const star of stars) {
                star[5] = star[3]
                star[6] = star[4]
                star[7] = 1
                star[2] -= speed
                if (star[2] < 0) {
                    star[2] += z
                    star[7] = 0
                }
                star[3] = cx + (star[0] / star[2]) * ratio
                star[4] = cy + (star[1] / star[2]) * ratio
            }

            // Draw
            ctx.fillStyle = bgColor
            ctx.fillRect(0, 0, w, h)
            ctx.strokeStyle = starColor

            for (const star of stars) {
                if (star[5] > 0 && star[5] < w && star[6] > 0 && star[6] < h && star[7]) {
                    ctx.lineWidth = (1 - (1 / z) * star[2]) * 2
                    ctx.beginPath()
                    ctx.moveTo(star[5], star[6])
                    ctx.lineTo(star[3], star[4])
                    ctx.stroke()
                }
            }

            animFrame = requestAnimationFrame(animate)
        }

        animate()

        return () => cancelAnimationFrame(animFrame)
    }, [speed, quantity, starColor, bgColor])

    return <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" />
}
