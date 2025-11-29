import { useCallback, useEffect, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import flappyHogSplashSrc from 'public/hedgehog/flappy-hog-splash.png'
import robotHogSrc from 'public/hedgehog/robot-hog.png'

const GAME_WIDTH = 450
const GAME_HEIGHT = 450
const HOG_SIZE = 50
const PIPE_WIDTH = 50
const PIPE_GAP = 180
const GRAVITY = 0.4
const FLAP_STRENGTH = -5
const PIPE_SPEED = 3
const PIPE_SPAWN_DISTANCE = 200
const HOG_X = GAME_WIDTH / 4
const HIGH_SCORE_KEY = 'flappyHogHighScore'

const COLORS = {
    background: '#1d1f27',
    pipe: '#f54e00',
    titleGlow: '#f54e00',
    titleMain: '#ffeb3b',
    textWhite: '#ffffff',
    textGray: '#cccccc',
    gameOverRed: '#ff0000',
    shadowBlack: 'rgba(0, 0, 0, 0.5)',
    overlayBlack: 'rgba(0, 0, 0, 0.6)',
    instructionShadow: 'rgba(0, 0, 0, 0.7)',
    fallbackHog: '#ffc107',
}

const FONTS = {
    title: 'bold 44px "Comic Sans MS", "Chalkboard SE", cursive',
    tagline: 'italic 14px "Comic Sans MS", "Chalkboard SE", cursive',
    instruction: 'bold 20px "Comic Sans MS", "Chalkboard SE", cursive',
    gameOver: 'bold 36px "Comic Sans MS", "Chalkboard SE", cursive',
    score: 'bold 28px "Comic Sans MS", "Chalkboard SE", cursive',
    scoreLarge: 'bold 24px "Comic Sans MS", "Chalkboard SE", cursive',
    scoreSmall: '14px "Comic Sans MS", "Chalkboard SE", cursive',
    playAgain: '18px "Comic Sans MS", "Chalkboard SE", cursive',
}

interface Pipe {
    x: number
    gapY: number
}

interface GameState {
    hogY: number
    hogVelocity: number
    pipes: Pipe[]
    distance: number
    gameOver: boolean
    started: boolean
}

function createInitialState(): GameState {
    return {
        hogY: GAME_HEIGHT / 2,
        hogVelocity: 0,
        pipes: [],
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
    return Math.floor(distance / 10)
}

function getHogBounds(hogY: number): { left: number; right: number; top: number; bottom: number } {
    return {
        left: HOG_X - HOG_SIZE / 2,
        right: HOG_X + HOG_SIZE / 2,
        top: hogY - HOG_SIZE / 2,
        bottom: hogY + HOG_SIZE / 2,
    }
}

function checkCollision(hogY: number, pipes: Pipe[]): boolean {
    const hog = getHogBounds(hogY)

    if (hog.top < 0 || hog.bottom > GAME_HEIGHT) {
        return true
    }

    return pipes.some(
        (pipe) =>
            hog.right > pipe.x &&
            hog.left < pipe.x + PIPE_WIDTH &&
            (hog.top < pipe.gapY || hog.bottom > pipe.gapY + PIPE_GAP)
    )
}

function updatePhysics(state: GameState): GameState {
    if (!state.started || state.gameOver) {
        return state
    }

    const newHogY = state.hogY + state.hogVelocity
    const newVelocity = state.hogVelocity + GRAVITY
    const newDistance = state.distance + 1

    let newPipes = state.pipes
        .map((pipe) => ({ ...pipe, x: pipe.x - PIPE_SPEED }))
        .filter((pipe) => pipe.x > -PIPE_WIDTH)

    const shouldSpawnPipe = newPipes.length === 0 || newPipes[newPipes.length - 1].x < GAME_WIDTH - PIPE_SPAWN_DISTANCE

    if (shouldSpawnPipe) {
        newPipes = [
            ...newPipes,
            {
                x: GAME_WIDTH,
                gapY: Math.random() * (GAME_HEIGHT - PIPE_GAP - 100) + 50,
            },
        ]
    }

    const gameOver = checkCollision(newHogY, newPipes)

    return {
        hogY: newHogY,
        hogVelocity: newVelocity,
        pipes: newPipes,
        distance: newDistance,
        gameOver,
        started: true,
    }
}

function drawBackground(ctx: CanvasRenderingContext2D): void {
    ctx.fillStyle = COLORS.background
    ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT)
}

function drawPipes(ctx: CanvasRenderingContext2D, pipes: Pipe[]): void {
    ctx.fillStyle = COLORS.pipe
    for (const pipe of pipes) {
        ctx.fillRect(pipe.x, 0, PIPE_WIDTH, pipe.gapY)
        ctx.fillRect(pipe.x, pipe.gapY + PIPE_GAP, PIPE_WIDTH, GAME_HEIGHT - pipe.gapY - PIPE_GAP)
    }
}

function drawHog(ctx: CanvasRenderingContext2D, hogY: number, hogImage: HTMLImageElement | null): void {
    const x = HOG_X - HOG_SIZE / 2
    const y = hogY - HOG_SIZE / 2

    if (hogImage?.complete) {
        ctx.drawImage(hogImage, x, y, HOG_SIZE, HOG_SIZE)
    } else {
        ctx.fillStyle = COLORS.fallbackHog
        ctx.beginPath()
        ctx.arc(HOG_X, hogY, HOG_SIZE / 2, 0, Math.PI * 2)
        ctx.fill()
    }
}

function drawTextWithShadow(
    ctx: CanvasRenderingContext2D,
    text: string,
    x: number,
    y: number,
    color: string,
    shadowColor: string,
    offsetX = 2,
    offsetY = 2
): void {
    ctx.fillStyle = shadowColor
    ctx.fillText(text, x + offsetX, y + offsetY)
    ctx.fillStyle = color
    ctx.fillText(text, x, y)
}

function drawTitleGlow(ctx: CanvasRenderingContext2D, text: string, x: number, y: number): void {
    ctx.fillStyle = COLORS.titleGlow
    ctx.fillText(text, x + 3, y)
    ctx.fillText(text, x - 3, y)
    ctx.fillText(text, x, y - 3)
    ctx.fillText(text, x, y + 3)
    ctx.fillStyle = COLORS.titleMain
    ctx.fillText(text, x, y)
}

function drawSplashScreen(ctx: CanvasRenderingContext2D, splashImage: HTMLImageElement | null): void {
    if (splashImage?.complete) {
        ctx.drawImage(splashImage, 0, 0, GAME_WIDTH, GAME_HEIGHT)
    }

    ctx.textAlign = 'center'
    ctx.font = FONTS.title
    drawTitleGlow(ctx, 'FLAPPY HOG', GAME_WIDTH / 2, 55)

    ctx.font = FONTS.tagline
    ctx.fillStyle = COLORS.textWhite
    ctx.fillText('★ Fly towards business-critical insights! ★', GAME_WIDTH / 2, 80)

    ctx.font = FONTS.instruction
    drawTextWithShadow(
        ctx,
        '~ Click or Press Space ~',
        GAME_WIDTH / 2,
        GAME_HEIGHT - 25,
        COLORS.textWhite,
        COLORS.instructionShadow
    )
}

function drawGameOverScreen(ctx: CanvasRenderingContext2D, score: number, highScore: number): void {
    ctx.fillStyle = COLORS.overlayBlack
    ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT)

    ctx.textAlign = 'center'
    ctx.font = FONTS.gameOver

    if (score >= highScore && score > 0) {
        drawTextWithShadow(
            ctx,
            'NEW HIGH SCORE!',
            GAME_WIDTH / 2,
            GAME_HEIGHT / 2 - 54,
            COLORS.titleMain,
            COLORS.titleGlow
        )
    }

    drawTextWithShadow(ctx, 'GAME OVER', GAME_WIDTH / 2, GAME_HEIGHT / 2 - 10, COLORS.textWhite, COLORS.gameOverRed)

    ctx.font = FONTS.scoreLarge
    ctx.fillStyle = COLORS.titleMain
    ctx.fillText(`Score: ${score}`, GAME_WIDTH / 2, GAME_HEIGHT / 2 + 30)

    ctx.font = FONTS.playAgain
    ctx.fillStyle = COLORS.textGray
    ctx.fillText('~ Click to Play Again ~', GAME_WIDTH / 2, GAME_HEIGHT / 2 + 65)
}

function drawScoreHUD(ctx: CanvasRenderingContext2D, score: number, highScore: number): void {
    ctx.textAlign = 'center'
    ctx.font = FONTS.score
    drawTextWithShadow(ctx, String(score), GAME_WIDTH / 2, 40, COLORS.textWhite, COLORS.shadowBlack)

    if (highScore > 0) {
        ctx.font = FONTS.scoreSmall
        ctx.fillStyle = COLORS.textGray
        ctx.fillText(`Best: ${highScore}`, GAME_WIDTH / 2, 60)
    }
}

function drawGame(
    ctx: CanvasRenderingContext2D,
    state: GameState,
    highScore: number,
    hogImage: HTMLImageElement | null,
    splashImage: HTMLImageElement | null
): void {
    drawBackground(ctx)
    drawPipes(ctx, state.pipes)
    drawHog(ctx, state.hogY, hogImage)

    const score = calculateScore(state.distance)

    if (!state.started) {
        drawSplashScreen(ctx, splashImage)
    } else if (state.gameOver) {
        drawGameOverScreen(ctx, score, highScore)
    } else {
        drawScoreHUD(ctx, score, highScore)
    }
}

export function FlappyHogGame({ isActive = true }: { isActive?: boolean }): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const gameLoopRef = useRef<number | null>(null)
    const gameStateRef = useRef<GameState>(createInitialState())
    const highScoreRef = useRef(getHighScore())
    const hogImageRef = useRef<HTMLImageElement | null>(null)
    const splashImageRef = useRef<HTMLImageElement | null>(null)

    const [highScore, setHighScore] = useState(getHighScore)

    useEffect(() => {
        const hog = new Image()
        hog.src = robotHogSrc
        hogImageRef.current = hog

        const splash = new Image()
        splash.src = flappyHogSplashSrc
        splashImageRef.current = splash
    }, [])

    const resetGame = useCallback(() => {
        gameStateRef.current = createInitialState()
    }, [])

    const handleClearHighScore = useCallback(() => {
        clearHighScore()
        setHighScore(0)
        highScoreRef.current = 0
    }, [])

    const flap = useCallback(() => {
        const state = gameStateRef.current
        if (state.gameOver) {
            resetGame()
            return
        }
        gameStateRef.current = {
            ...state,
            started: true,
            hogVelocity: FLAP_STRENGTH,
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

                const prevState = gameStateRef.current
                const newState = updatePhysics(prevState)

                if (newState.gameOver && !prevState.gameOver) {
                    const finalScore = calculateScore(newState.distance)
                    if (finalScore > highScoreRef.current) {
                        saveHighScore(finalScore)
                        setHighScore(finalScore)
                        highScoreRef.current = finalScore
                    }
                }

                gameStateRef.current = newState
                drawGame(currentCtx, newState, highScoreRef.current, hogImageRef.current, splashImageRef.current)
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
                flap()
            }
        }
        window.addEventListener('keydown', handleKeyDown)
        return () => window.removeEventListener('keydown', handleKeyDown)
    }, [isActive, flap])

    return (
        <div className="flex flex-col items-center">
            <canvas
                ref={canvasRef}
                width={GAME_WIDTH}
                height={GAME_HEIGHT}
                onClick={flap}
                className="cursor-pointer rounded border border-border"
            />
            {highScore > 0 && (
                <div className="mt-4">
                    <LemonButton type="tertiary" size="small" onClick={handleClearHighScore}>
                        Clear high score
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

export function FlappyHog({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="Flappy Hog" simple>
            <div className="flex flex-col items-center p-4">
                <FlappyHogGame isActive={isOpen} />
                <div className="mt-4">
                    <LemonButton onClick={onClose}>Close</LemonButton>
                </div>
            </div>
        </LemonModal>
    )
}
