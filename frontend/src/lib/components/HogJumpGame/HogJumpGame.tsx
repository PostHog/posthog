import { useCallback, useEffect, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import runningHogSrc from 'public/hedgehog/running-hog.png'

const GAME_WIDTH = 600
const GAME_HEIGHT = 150
const HOG_SIZE = 50
const HOG_X = 50
const GROUND_Y = GAME_HEIGHT - 20
const GRAVITY = 0.8
const JUMP_STRENGTH = -12
const OBSTACLE_SPEED = 6
const OBSTACLE_SPAWN_MIN = 80
const OBSTACLE_SPAWN_MAX = 200
const HIGH_SCORE_KEY = 'hogJumpHighScore'

const COLORS = {
    background: '#1d1f27',
    ground: '#3d3f47',
    groundLine: '#5d5f67',
    fireOuter: '#f54e00',
    fireMiddle: '#ff8c00',
    fireInner: '#ffeb3b',
    textWhite: '#ffffff',
    textGray: '#aaaaaa',
    shadowBlack: 'rgba(0, 0, 0, 0.5)',
    fallbackHog: '#ffc107',
}

const FONTS = {
    title: 'bold 18px Inter, sans-serif',
    score: 'bold 16px Inter, monospace',
    instruction: '14px Inter, sans-serif',
    gameOver: 'bold 20px Inter, sans-serif',
}

interface Obstacle {
    x: number
    width: number
    height: number
}

interface GameState {
    hogY: number
    hogVelocity: number
    isJumping: boolean
    obstacles: Obstacle[]
    distance: number
    gameOver: boolean
    started: boolean
}

function createInitialState(): GameState {
    return {
        hogY: GROUND_Y - HOG_SIZE,
        hogVelocity: 0,
        isJumping: false,
        obstacles: [],
        distance: 0,
        gameOver: false,
        started: false,
    }
}

function getHighScore(): number {
    try {
        return parseInt(localStorage.getItem(HIGH_SCORE_KEY) || '0', 10)
    } catch {
        return 0
    }
}

function saveHighScore(score: number): void {
    try {
        localStorage.setItem(HIGH_SCORE_KEY, String(score))
    } catch {
        // Storage unavailable
    }
}

function clearHighScore(): void {
    try {
        localStorage.removeItem(HIGH_SCORE_KEY)
    } catch {
        // Storage unavailable
    }
}

function calculateScore(distance: number): number {
    return Math.floor(distance / 5)
}

function createObstacle(): Obstacle {
    const height = 20 + Math.random() * 30
    return {
        x: GAME_WIDTH,
        width: 15 + Math.random() * 10,
        height,
    }
}

function checkCollision(hogY: number, obstacles: Obstacle[]): boolean {
    const hogLeft = HOG_X
    const hogRight = HOG_X + HOG_SIZE * 0.7
    const hogTop = hogY
    const hogBottom = hogY + HOG_SIZE

    return obstacles.some((obs) => {
        const obsLeft = obs.x
        const obsRight = obs.x + obs.width
        const obsTop = GROUND_Y - obs.height
        const obsBottom = GROUND_Y

        return hogRight > obsLeft && hogLeft < obsRight && hogBottom > obsTop && hogTop < obsBottom
    })
}

function updatePhysics(state: GameState, nextSpawnDistance: number): { state: GameState; nextSpawn: number } {
    if (!state.started || state.gameOver) {
        return { state, nextSpawn: nextSpawnDistance }
    }

    let newHogY = state.hogY
    let newVelocity = state.hogVelocity
    let newIsJumping = state.isJumping

    if (state.isJumping) {
        newVelocity += GRAVITY
        newHogY += newVelocity

        if (newHogY >= GROUND_Y - HOG_SIZE) {
            newHogY = GROUND_Y - HOG_SIZE
            newVelocity = 0
            newIsJumping = false
        }
    }

    const newDistance = state.distance + 1

    let newObstacles = state.obstacles
        .map((obs) => ({ ...obs, x: obs.x - OBSTACLE_SPEED }))
        .filter((obs) => obs.x > -obs.width)

    let newNextSpawn = nextSpawnDistance
    if (newDistance >= nextSpawnDistance) {
        newObstacles = [...newObstacles, createObstacle()]
        newNextSpawn = newDistance + OBSTACLE_SPAWN_MIN + Math.random() * (OBSTACLE_SPAWN_MAX - OBSTACLE_SPAWN_MIN)
    }

    const gameOver = checkCollision(newHogY, newObstacles)

    return {
        state: {
            hogY: newHogY,
            hogVelocity: newVelocity,
            isJumping: newIsJumping,
            obstacles: newObstacles,
            distance: newDistance,
            gameOver,
            started: true,
        },
        nextSpawn: newNextSpawn,
    }
}

function drawBackground(ctx: CanvasRenderingContext2D): void {
    ctx.fillStyle = COLORS.background
    ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT)

    // Ground
    ctx.fillStyle = COLORS.ground
    ctx.fillRect(0, GROUND_Y, GAME_WIDTH, GAME_HEIGHT - GROUND_Y)

    // Ground line
    ctx.strokeStyle = COLORS.groundLine
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(0, GROUND_Y)
    ctx.lineTo(GAME_WIDTH, GROUND_Y)
    ctx.stroke()
}

function drawFlame(
    ctx: CanvasRenderingContext2D,
    x: number,
    baseY: number,
    width: number,
    height: number,
    frame: number,
    seed: number
): void {
    const centerX = x + width / 2
    const flickerOffset = Math.sin(frame * 0.3 + seed) * 2
    const flickerHeight = Math.sin(frame * 0.2 + seed * 2) * 3

    // Outer flame (red-orange)
    ctx.fillStyle = COLORS.fireOuter
    ctx.beginPath()
    ctx.moveTo(x, baseY)
    ctx.quadraticCurveTo(
        x - 3 + flickerOffset,
        baseY - height * 0.6,
        centerX + flickerOffset,
        baseY - height - flickerHeight
    )
    ctx.quadraticCurveTo(x + width + 3 + flickerOffset, baseY - height * 0.6, x + width, baseY)
    ctx.closePath()
    ctx.fill()

    // Middle flame (orange)
    ctx.fillStyle = COLORS.fireMiddle
    ctx.beginPath()
    const midWidth = width * 0.7
    const midX = x + (width - midWidth) / 2
    ctx.moveTo(midX, baseY)
    ctx.quadraticCurveTo(
        midX - 2 - flickerOffset,
        baseY - height * 0.5,
        centerX - flickerOffset,
        baseY - height * 0.75 - flickerHeight
    )
    ctx.quadraticCurveTo(midX + midWidth + 2 - flickerOffset, baseY - height * 0.5, midX + midWidth, baseY)
    ctx.closePath()
    ctx.fill()

    // Inner flame (yellow)
    ctx.fillStyle = COLORS.fireInner
    ctx.beginPath()
    const innerWidth = width * 0.4
    const innerX = x + (width - innerWidth) / 2
    ctx.moveTo(innerX, baseY)
    ctx.quadraticCurveTo(
        innerX + flickerOffset,
        baseY - height * 0.3,
        centerX + flickerOffset * 0.5,
        baseY - height * 0.5 - flickerHeight
    )
    ctx.quadraticCurveTo(innerX + innerWidth + flickerOffset, baseY - height * 0.3, innerX + innerWidth, baseY)
    ctx.closePath()
    ctx.fill()
}

function drawObstacles(ctx: CanvasRenderingContext2D, obstacles: Obstacle[], frame: number): void {
    for (const obs of obstacles) {
        // Use x position as a seed for consistent but varied animation per flame
        const seed = obs.x * 0.1
        drawFlame(ctx, obs.x, GROUND_Y, obs.width, obs.height, frame, seed)
    }
}

function drawHog(ctx: CanvasRenderingContext2D, hogY: number, hogImage: HTMLImageElement | null, frame: number): void {
    const x = HOG_X
    const y = hogY

    if (hogImage?.complete) {
        ctx.save()
        // Add a slight bob when running on ground
        const bobOffset = hogY === GROUND_Y - HOG_SIZE ? Math.sin(frame * 0.3) * 2 : 0
        ctx.drawImage(hogImage, x, y + bobOffset, HOG_SIZE, HOG_SIZE)
        ctx.restore()
    } else {
        ctx.fillStyle = COLORS.fallbackHog
        ctx.beginPath()
        ctx.arc(x + HOG_SIZE / 2, hogY + HOG_SIZE / 2, HOG_SIZE / 2, 0, Math.PI * 2)
        ctx.fill()
    }
}

function drawStartScreen(ctx: CanvasRenderingContext2D): void {
    ctx.fillStyle = COLORS.shadowBlack
    ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT)

    ctx.textAlign = 'center'
    ctx.fillStyle = COLORS.textWhite
    ctx.font = FONTS.title
    ctx.fillText("Something's not quite right...", GAME_WIDTH / 2, 50)

    ctx.font = FONTS.instruction
    ctx.fillStyle = COLORS.textGray
    ctx.fillText('Press SPACE or click to jump', GAME_WIDTH / 2, 80)
}

function drawGameOver(ctx: CanvasRenderingContext2D, score: number, highScore: number): void {
    ctx.fillStyle = COLORS.shadowBlack
    ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT)

    ctx.textAlign = 'center'
    ctx.fillStyle = COLORS.textWhite
    ctx.font = FONTS.gameOver
    ctx.fillText('GAME OVER', GAME_WIDTH / 2, 50)

    ctx.font = FONTS.score
    ctx.fillText(`Score: ${score}`, GAME_WIDTH / 2, 80)

    if (score >= highScore && score > 0) {
        ctx.fillStyle = COLORS.fireMiddle
        ctx.fillText('NEW HIGH SCORE!', GAME_WIDTH / 2, 100)
    }

    ctx.font = FONTS.instruction
    ctx.fillStyle = COLORS.textGray
    ctx.fillText('Press SPACE or click to retry', GAME_WIDTH / 2, 125)
}

function drawScoreHUD(ctx: CanvasRenderingContext2D, score: number, highScore: number): void {
    ctx.textAlign = 'right'
    ctx.font = FONTS.score
    ctx.fillStyle = COLORS.textWhite
    ctx.fillText(`${String(score).padStart(5, '0')}`, GAME_WIDTH - 10, 25)

    if (highScore > 0) {
        ctx.fillStyle = COLORS.textGray
        ctx.fillText(`HI ${String(highScore).padStart(5, '0')}`, GAME_WIDTH - 80, 25)
    }
}

function drawGame(
    ctx: CanvasRenderingContext2D,
    state: GameState,
    highScore: number,
    hogImage: HTMLImageElement | null,
    frame: number
): void {
    drawBackground(ctx)
    drawObstacles(ctx, state.obstacles, frame)
    drawHog(ctx, state.hogY, hogImage, frame)

    const score = calculateScore(state.distance)

    if (!state.started) {
        drawStartScreen(ctx)
    } else if (state.gameOver) {
        drawGameOver(ctx, score, highScore)
    } else {
        drawScoreHUD(ctx, score, highScore)
    }
}

export interface HogJumpGameProps {
    isActive?: boolean
    title?: string
    subtitle?: string
}

export function HogJumpGame({
    isActive = true,
    title = "Something's not quite right...",
    subtitle,
}: HogJumpGameProps): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const gameLoopRef = useRef<number | null>(null)
    const gameStateRef = useRef<GameState>(createInitialState())
    const highScoreRef = useRef(getHighScore())
    const hogImageRef = useRef<HTMLImageElement | null>(null)
    const nextSpawnRef = useRef(OBSTACLE_SPAWN_MIN)
    const frameRef = useRef(0)

    const [highScore, setHighScore] = useState(getHighScore)

    useEffect(() => {
        const hog = new Image()
        hog.src = runningHogSrc
        hogImageRef.current = hog
    }, [])

    const resetGame = useCallback(() => {
        gameStateRef.current = createInitialState()
        nextSpawnRef.current = OBSTACLE_SPAWN_MIN
    }, [])

    const handleClearHighScore = useCallback(() => {
        clearHighScore()
        setHighScore(0)
        highScoreRef.current = 0
    }, [])

    const jump = useCallback(() => {
        const state = gameStateRef.current
        if (state.gameOver) {
            resetGame()
            return
        }
        if (!state.isJumping) {
            gameStateRef.current = {
                ...state,
                started: true,
                isJumping: true,
                hogVelocity: JUMP_STRENGTH,
            }
        }
    }, [resetGame])

    useEffect(() => {
        if (!isActive) {
            resetGame()
            if (gameLoopRef.current) {
                cancelAnimationFrame(gameLoopRef.current)
                gameLoopRef.current = null
            }
            return
        }

        const startTimeout = setTimeout(() => {
            const canvas = canvasRef.current
            const ctx = canvas?.getContext('2d')
            if (!canvas || !ctx) {
                return
            }

            const gameLoop = (): void => {
                const currentCanvas = canvasRef.current
                const currentCtx = currentCanvas?.getContext('2d')
                if (!currentCanvas || !currentCtx) {
                    return
                }

                frameRef.current += 1

                const prevState = gameStateRef.current
                const { state: newState, nextSpawn } = updatePhysics(prevState, nextSpawnRef.current)
                nextSpawnRef.current = nextSpawn

                if (newState.gameOver && !prevState.gameOver) {
                    const finalScore = calculateScore(newState.distance)
                    if (finalScore > highScoreRef.current) {
                        saveHighScore(finalScore)
                        setHighScore(finalScore)
                        highScoreRef.current = finalScore
                    }
                }

                gameStateRef.current = newState
                drawGame(currentCtx, newState, highScoreRef.current, hogImageRef.current, frameRef.current)
                gameLoopRef.current = requestAnimationFrame(gameLoop)
            }

            gameLoopRef.current = requestAnimationFrame(gameLoop)
        }, 50)

        return () => {
            clearTimeout(startTimeout)
            if (gameLoopRef.current) {
                cancelAnimationFrame(gameLoopRef.current)
            }
        }
    }, [isActive, resetGame])

    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent): void => {
            if (isActive && (e.code === 'Space' || e.code === 'ArrowUp')) {
                e.preventDefault()
                jump()
            }
        }
        window.addEventListener('keydown', handleKeyDown)
        return () => window.removeEventListener('keydown', handleKeyDown)
    }, [isActive, jump])

    return (
        <div className="flex flex-col items-center gap-4">
            {title && <h2 className="text-xl font-bold m-0">{title}</h2>}
            {subtitle && <p className="text-muted m-0">{subtitle}</p>}
            <canvas
                ref={canvasRef}
                width={GAME_WIDTH}
                height={GAME_HEIGHT}
                onClick={jump}
                className="cursor-pointer rounded border border-border"
            />
            {highScore > 0 && (
                <LemonButton type="tertiary" size="small" onClick={handleClearHighScore}>
                    Clear high score
                </LemonButton>
            )}
        </div>
    )
}

export default HogJumpGame
