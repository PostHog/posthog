import { useCallback, useEffect, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import professorHogSrc from 'public/hedgehog/professor-hog.png'

interface GameState {
    hogY: number
    hogVelocity: number
    pipes: { x: number; gapY: number }[]
    distance: number
    gameOver: boolean
    started: boolean
}

const GAME_WIDTH = 400
const GAME_HEIGHT = 500
const HOG_SIZE = 50
const PIPE_WIDTH = 50
const PIPE_GAP = 180
const GRAVITY = 0.4
const FLAP_STRENGTH = -6
const PIPE_SPEED = 3

export function FlappyHog({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const gameLoopRef = useRef<number | null>(null)
    const hogImageRef = useRef<HTMLImageElement | null>(null)
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
        img.src = professorHogSrc
        hogImageRef.current = img
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

                // Draw professor hog
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

                // Draw distance score
                const displayScore = Math.floor(gameStateRef.current.distance / 10)
                currentCtx.fillStyle = '#ffffff'
                currentCtx.font = 'bold 24px sans-serif'
                currentCtx.textAlign = 'center'
                currentCtx.fillText(String(displayScore), GAME_WIDTH / 2, 40)

                // Draw instructions or game over
                if (!gameStateRef.current.started) {
                    currentCtx.fillStyle = 'rgba(0, 0, 0, 0.5)'
                    currentCtx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT)
                    currentCtx.fillStyle = '#ffffff'
                    currentCtx.font = 'bold 20px sans-serif'
                    currentCtx.fillText('Click to start!', GAME_WIDTH / 2, GAME_HEIGHT / 2)
                } else if (gameStateRef.current.gameOver) {
                    currentCtx.fillStyle = 'rgba(0, 0, 0, 0.5)'
                    currentCtx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT)
                    currentCtx.fillStyle = '#ffffff'
                    currentCtx.font = 'bold 24px sans-serif'
                    currentCtx.fillText('Game Over!', GAME_WIDTH / 2, GAME_HEIGHT / 2 - 20)
                    currentCtx.font = '18px sans-serif'
                    currentCtx.fillText(`Score: ${displayScore}`, GAME_WIDTH / 2, GAME_HEIGHT / 2 + 10)
                    currentCtx.fillText('Click to play again', GAME_WIDTH / 2, GAME_HEIGHT / 2 + 40)
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
                <p className="text-muted text-sm mt-2">
                    Click or press Space to fly towards business-critical insights
                </p>
                <LemonButton onClick={onClose} className="mt-4">
                    Close
                </LemonButton>
            </div>
        </LemonModal>
    )
}
