import { useCallback, useEffect, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import flappyHogSplashSrc from 'public/hedgehog/flappy-hog-splash.png'
import robotHogSrc from 'public/hedgehog/robot-hog.png'

interface GameState {
    hogY: number
    hogVelocity: number
    pipes: { x: number; gapY: number }[]
    distance: number
    gameOver: boolean
    started: boolean
}

const GAME_WIDTH = 450
const GAME_HEIGHT = 450
const HOG_SIZE = 50
const PIPE_WIDTH = 50
const PIPE_GAP = 180
const GRAVITY = 0.4
const FLAP_STRENGTH = -5
const PIPE_SPEED = 3
const HIGH_SCORE_KEY = 'flappyHogHighScore'

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
        // ignore
    }
}

function clearHighScore(): void {
    try {
        localStorage.removeItem(HIGH_SCORE_KEY)
    } catch {
        // ignore
    }
}

export function FlappyHog({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const gameLoopRef = useRef<number | null>(null)
    const hogImageRef = useRef<HTMLImageElement | null>(null)
    const splashImageRef = useRef<HTMLImageElement | null>(null)
    const [highScore, setHighScoreState] = useState(getHighScore)
    const highScoreRef = useRef(highScore)
    highScoreRef.current = highScore
    const [gameState, setGameState] = useState<GameState>({
        hogY: GAME_HEIGHT / 2,
        hogVelocity: 0,
        pipes: [],
        distance: 0,
        gameOver: false,
        started: false,
    })
    const gameStateRef = useRef(gameState)
    gameStateRef.current = gameState

    const handleClearHighScore = useCallback(() => {
        clearHighScore()
        setHighScoreState(0)
    }, [])

    const resetGame = useCallback(() => {
        setGameState({
            hogY: GAME_HEIGHT / 2,
            hogVelocity: 0,
            pipes: [],
            distance: 0,
            gameOver: false,
            started: false,
        })
    }, [])

    const flap = useCallback(() => {
        if (gameStateRef.current.gameOver) {
            resetGame()
            return
        }
        setGameState((prev) => ({
            ...prev,
            started: true,
            hogVelocity: FLAP_STRENGTH,
        }))
    }, [resetGame])

    useEffect(() => {
        const img = new Image()
        img.src = robotHogSrc
        hogImageRef.current = img

        const splashImg = new Image()
        splashImg.src = flappyHogSplashSrc
        splashImageRef.current = splashImg
    }, [])

    useEffect(() => {
        if (!isOpen) {
            resetGame()
            if (gameLoopRef.current) {
                cancelAnimationFrame(gameLoopRef.current)
                gameLoopRef.current = null
            }
            return
        }

        const startTimeout = setTimeout(() => {
            const canvas = canvasRef.current
            if (!canvas) {
                return
            }
            const ctx = canvas.getContext('2d')
            if (!ctx) {
                return
            }

            const gameLoop = (): void => {
                const currentCanvas = canvasRef.current
                const currentCtx = currentCanvas?.getContext('2d')
                if (!currentCanvas || !currentCtx) {
                    return
                }

                const state = gameStateRef.current

                if (!state.gameOver && state.started) {
                    let newHogY = state.hogY + state.hogVelocity
                    let newVelocity = state.hogVelocity + GRAVITY
                    let newPipes = [...state.pipes]
                    let newDistance = state.distance + 1
                    let gameOver = false

                    if (newPipes.length === 0 || newPipes[newPipes.length - 1].x < GAME_WIDTH - 200) {
                        newPipes.push({
                            x: GAME_WIDTH,
                            gapY: Math.random() * (GAME_HEIGHT - PIPE_GAP - 100) + 50,
                        })
                    }

                    newPipes = newPipes
                        .map((pipe) => ({ ...pipe, x: pipe.x - PIPE_SPEED }))
                        .filter((pipe) => pipe.x > -PIPE_WIDTH)

                    const hogLeft = GAME_WIDTH / 4 - HOG_SIZE / 2
                    const hogRight = hogLeft + HOG_SIZE
                    const hogTop = newHogY - HOG_SIZE / 2
                    const hogBottom = newHogY + HOG_SIZE / 2

                    if (hogTop < 0 || hogBottom > GAME_HEIGHT) {
                        gameOver = true
                    }

                    for (const pipe of newPipes) {
                        if (hogRight > pipe.x && hogLeft < pipe.x + PIPE_WIDTH) {
                            if (hogTop < pipe.gapY || hogBottom > pipe.gapY + PIPE_GAP) {
                                gameOver = true
                            }
                        }
                    }

                    if (gameOver) {
                        const finalScore = Math.floor(newDistance / 10)
                        if (finalScore > highScoreRef.current) {
                            saveHighScore(finalScore)
                            setHighScoreState(finalScore)
                        }
                    }

                    setGameState({
                        hogY: newHogY,
                        hogVelocity: newVelocity,
                        pipes: newPipes,
                        distance: newDistance,
                        gameOver,
                        started: true,
                    })
                }

                // Draw background
                currentCtx.fillStyle = '#1d1f27'
                currentCtx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT)

                // Draw pipes
                currentCtx.fillStyle = '#f54e00'
                for (const pipe of gameStateRef.current.pipes) {
                    currentCtx.fillRect(pipe.x, 0, PIPE_WIDTH, pipe.gapY)
                    currentCtx.fillRect(pipe.x, pipe.gapY + PIPE_GAP, PIPE_WIDTH, GAME_HEIGHT - pipe.gapY - PIPE_GAP)
                }

                // Draw robot hog
                const hogX = GAME_WIDTH / 4
                const hogY = gameStateRef.current.hogY
                if (hogImageRef.current && hogImageRef.current.complete) {
                    currentCtx.drawImage(
                        hogImageRef.current,
                        hogX - HOG_SIZE / 2,
                        hogY - HOG_SIZE / 2,
                        HOG_SIZE,
                        HOG_SIZE
                    )
                } else {
                    currentCtx.fillStyle = '#ffc107'
                    currentCtx.beginPath()
                    currentCtx.arc(hogX, hogY, HOG_SIZE / 2, 0, Math.PI * 2)
                    currentCtx.fill()
                }

                const displayScore = Math.floor(gameStateRef.current.distance / 10)
                currentCtx.textAlign = 'center'

                // Draw splash screen, score HUD, or game over
                if (!gameStateRef.current.started) {
                    if (splashImageRef.current && splashImageRef.current.complete) {
                        currentCtx.drawImage(splashImageRef.current, 0, 0, GAME_WIDTH, GAME_HEIGHT)
                    }
                    // Retro title with glow effect
                    currentCtx.font = 'bold 44px "Comic Sans MS", "Chalkboard SE", cursive'
                    // Outer glow
                    currentCtx.fillStyle = '#f54e00'
                    currentCtx.fillText('FLAPPY HOG', GAME_WIDTH / 2 + 3, 55)
                    currentCtx.fillText('FLAPPY HOG', GAME_WIDTH / 2 - 3, 55)
                    currentCtx.fillText('FLAPPY HOG', GAME_WIDTH / 2, 52)
                    currentCtx.fillText('FLAPPY HOG', GAME_WIDTH / 2, 58)
                    // Main text
                    currentCtx.fillStyle = '#ffeb3b'
                    currentCtx.fillText('FLAPPY HOG', GAME_WIDTH / 2, 55)
                    // Tagline with stars
                    currentCtx.font = 'italic 14px "Comic Sans MS", "Chalkboard SE", cursive'
                    currentCtx.fillStyle = '#ffffff'
                    currentCtx.fillText('★ Fly towards business-critical insights! ★', GAME_WIDTH / 2, 80)
                    // "Click to play" at bottom with retro style
                    currentCtx.font = 'bold 20px "Comic Sans MS", "Chalkboard SE", cursive'
                    currentCtx.fillStyle = 'rgba(0, 0, 0, 0.7)'
                    currentCtx.fillText('~ Click or Press Space ~', GAME_WIDTH / 2 + 2, GAME_HEIGHT - 23)
                    currentCtx.fillStyle = '#ffffff'
                    currentCtx.fillText('~ Click or Press Space ~', GAME_WIDTH / 2, GAME_HEIGHT - 25)
                } else if (gameStateRef.current.gameOver) {
                    currentCtx.fillStyle = 'rgba(0, 0, 0, 0.6)'
                    currentCtx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT)
                    // Retro game over text
                    currentCtx.font = 'bold 36px "Comic Sans MS", "Chalkboard SE", cursive'
                    if (displayScore >= highScoreRef.current && displayScore > 0) {
                        currentCtx.fillStyle = '#f54e00'
                        currentCtx.fillText('NEW HIGH SCORE!', GAME_WIDTH / 2 + 2, GAME_HEIGHT / 2 - 52)
                        currentCtx.fillStyle = '#ffeb3b'
                        currentCtx.fillText('NEW HIGH SCORE!', GAME_WIDTH / 2, GAME_HEIGHT / 2 - 54)
                    }
                    currentCtx.fillStyle = '#ff0000'
                    currentCtx.fillText('GAME OVER', GAME_WIDTH / 2 + 2, GAME_HEIGHT / 2 - 8)
                    currentCtx.fillStyle = '#ffffff'
                    currentCtx.fillText('GAME OVER', GAME_WIDTH / 2, GAME_HEIGHT / 2 - 10)
                    currentCtx.font = 'bold 24px "Comic Sans MS", "Chalkboard SE", cursive'
                    currentCtx.fillStyle = '#ffeb3b'
                    currentCtx.fillText(`Score: ${displayScore}`, GAME_WIDTH / 2, GAME_HEIGHT / 2 + 30)
                    currentCtx.font = '18px "Comic Sans MS", "Chalkboard SE", cursive'
                    currentCtx.fillStyle = '#cccccc'
                    currentCtx.fillText('~ Click to Play Again ~', GAME_WIDTH / 2, GAME_HEIGHT / 2 + 65)
                } else {
                    // Game is running - show score HUD with retro style
                    currentCtx.font = 'bold 28px "Comic Sans MS", "Chalkboard SE", cursive'
                    // Score shadow
                    currentCtx.fillStyle = 'rgba(0, 0, 0, 0.5)'
                    currentCtx.fillText(String(displayScore), GAME_WIDTH / 2 + 2, 42)
                    currentCtx.fillStyle = '#ffffff'
                    currentCtx.fillText(String(displayScore), GAME_WIDTH / 2, 40)
                    if (highScoreRef.current > 0) {
                        currentCtx.font = '14px "Comic Sans MS", "Chalkboard SE", cursive'
                        currentCtx.fillStyle = '#cccccc'
                        currentCtx.fillText(`Best: ${highScoreRef.current}`, GAME_WIDTH / 2, 60)
                    }
                }

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
    }, [isOpen, resetGame])

    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent): void => {
            if (isOpen && (e.code === 'Space' || e.code === 'ArrowUp')) {
                e.preventDefault()
                flap()
            }
        }
        window.addEventListener('keydown', handleKeyDown)
        return () => window.removeEventListener('keydown', handleKeyDown)
    }, [isOpen, flap])

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="Flappy Hog" simple>
            <div className="flex flex-col items-center p-4">
                <canvas
                    ref={canvasRef}
                    width={GAME_WIDTH}
                    height={GAME_HEIGHT}
                    onClick={flap}
                    className="cursor-pointer rounded border border-border"
                />
                <div className="flex gap-2 mt-4">
                    <LemonButton onClick={onClose}>Close</LemonButton>
                    {highScore > 0 && (
                        <LemonButton type="tertiary" size="small" onClick={handleClearHighScore}>
                            Clear high score
                        </LemonButton>
                    )}
                </div>
            </div>
        </LemonModal>
    )
}
