import chalk from 'chalk'

interface HedgehogOptions {
    speed: number
    count: number
}

interface Hedgehog {
    x: number
    y: number
    direction: number // 1 for right, -1 for left
    frameType: number // which hedgehog design to use
    animationFrame: number // animation cycle within that design
    color: string
    width: number
    height: number
}

// Hedgehog animation frames - ready for new ASCII designs
const hedgehogFrames = [
    // Placeholder frame - will be replaced with your new designs
    [
        '⠀⠀⠀⠀⠀⠀⢠⠠⣆⢆⢶⢴⢄⣦⢊⠴⡘⢆⢤⡞⢢⡤⠀⠀⠀⠀⠀⠀⠀⠀',
        '⠀⠀⠀⠀⠀⢦⡝⣇⠻⡘⠄⠀⡸⠊⠀⠀⠀⠀⠀⠀⠀⠐⠁⠒⣤⠀⠀⠀⠀⠀',
        '⠀⠀⠀⢀⣴⡄⠁⡈⠀⡇⡃⡐⠀⠀⠀⠀⢀⡀⠀⠀⠀⠀⣀⠀⠻⣧⣄⡀⠀⠀',
        '⠀⠀⠀⠀⠙⣿⡌⣉⡀⠀⢠⠁⠀⢀⠄⡠⠏⠀⠀⠂⠁⠁⢀⡀⠀⠀⠸⠿⡀⠀',
        '⠀⠀⠀⠀⠀⣿⠓⢿⣧⣾⠷⢅⠀⠀⠀⠀⣠⡇⠀⢀⠄⠘⠋⠀⠀⠀⠀⠀⠿⠄',
        '⠀⠀⠀⢀⠎⠀⠀⠄⠈⠁⢁⣅⠇⢀⣀⣨⠁⠀⡠⠋⠀⢠⠴⢂⡔⢦⡈⣑⢄⠀',
        '⠀⠀⡠⠊⠀⣶⡄⠀⠀⠀⡚⠋⠛⠿⠭⣤⢖⣋⠀⠀⢀⡀⠄⠑⠂⣀⠀⠀⠛⠅',
        '⣴⡏⠀⠀⠀⠉⠁⠀⠀⠄⠃⠀⠀⠀⠀⠀⠀⠉⠉⠃⠾⠗⣆⣳⡄⠀⠉⠀⠹⢥',
        '⠀⠃⠠⠤⠀⠀⠀⠐⠋⠀⠀⡀⢀⠀⠀⠀⠀⠀⠰⣦⠀⠀⢀⠙⠻⠂⣸⣧⡱⡂',
        '⠀⠀⠀⠀⠀⠀⠀⠀⠀⡆⠑⠰⠆⡀⢠⣐⠀⢀⠀⠀⠀⠂⡄⠁⢀⢀⠾⠉⠀⠉',
        '⠀⠀⠀⠀⠀⠀⠀⠺⠭⠤⢢⡄⠂⣀⡠⠉⠉⠀⠉⠒⠚⣶⢃⡠⠞⠁⠀⠀⠀⠀',
        '⠀⠀⠀⠀⠀⠀⠀⠀⠀⠤⠤⠤⠤⠤⠤⠄⠀⠤⠤⠤⠄⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    ],
    [
        '⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
        '⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⣤⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
        '⠀⠀⠀⠀⠀⠀⠀⠻⠿⠿⠿⠀⠉⠛⠻⢷⠂⠻⣷⣄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
        '⠀⠀⠀⢀⣤⡶⠟⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠛⠃⠺⣧⡀⠀⠀⠀⠀⠀⠀',
        '⠀⠀⠀⢠⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⢿⣆⠀⠀⠀⠀⠀',
        '⠀⠀⣰⡟⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⣿⣿⣷⣀⣴⣾⣿⡄⠀⠀⠀⠀',
        '⠀⠰⠟⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⢿⣿⣿⡟⠉⠙⢿⣿⣄⠀⠀⠀',
        '⠀⠀⢸⣇⠀⠀⠀⢀⣀⣀⣀⣀⣀⣀⣀⣠⣤⣴⣿⣿⣿⣿⣶⣴⣿⣿⣿⣃⣀⠀',
        '⠀⠀⠀⢿⣀⣴⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠟⠃⠀',
        '⠀⠀⠀⠘⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠉⠉⠁⠀⠀⠀⠀',
        '⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    ],
    [
        '⠀⠀⠀⠀⠀⠀⠀⠀⠀⡀⢠⡀⡴⠰⡄⡔⢄⡰⢣⠔⡀⡠⠀⠀⠀⠀⠀⢀⠄⠠',
        '⠀⠀⠀⠀⠀⡄⠠⢇⠞⠙⣃⠈⠀⠁⠈⢀⡀⣀⢦⢄⠉⢀⠇⢒⠀⠀⠀⡸⣀⠐',
        '⠀⠀⠀⡤⠀⠱⠁⠀⠀⣀⢉⡂⠑⠢⡒⠀⢈⠀⢈⠀⢦⠼⠉⣈⡀⠈⠁⠀⠀⢘',
        '⠀⠀⠗⠴⡀⠀⠠⡲⠌⠀⠑⠘⠶⡒⠀⠑⢖⠈⣠⢖⠾⠂⢸⢿⣿⠀⠀⠀⠀⠌',
        '⢀⠡⠘⠀⠀⡉⠖⢀⠤⠊⠑⠀⡀⠐⠂⢁⡠⠉⠈⢮⣲⠂⠀⠁⠁⠀⠈⡖⠒⠰',
        '⢬⠯⠁⠐⠛⡀⠈⢉⣭⡒⢀⠭⠀⣀⠤⠈⣉⠆⠐⠢⣉⠀⠀⠀⠀⠀⠀⠀⠀⡘',
        '⢀⡱⠆⠐⠓⢂⠴⠍⢀⡰⠉⠥⣄⡂⢀⣜⣁⣥⣌⣫⡀⠀⠀⠀⠀⠀⠀⣠⠊⠀',
        '⠀⢎⡁⢀⠴⠅⡠⠒⠃⢀⡴⡅⢀⢔⠋⡴⢀⠰⡒⠓⠀⠀⠀⠀⠀⠀⡔⠁⠀⠀',
        '⠈⣹⡥⠀⠀⡜⣨⡂⣔⠥⡞⢂⠎⡅⣄⠰⢼⡉⠑⠀⠀⠀⠀⠀⢀⡜⠀⠀⠀⠀',
        '⠀⠀⠞⣙⠚⠖⠁⣜⢠⢤⠑⡌⠱⠉⠃⠙⠀⠁⢀⠀⠀⠀⣄⡠⠊⠀⠀⠀⠀⠀',
        '⠀⠀⠀⠎⢒⡾⡜⠀⡡⠊⠹⡲⠤⢀⣀⣀⣀⡀⠼⠀⠀⠀⢫⡐⢀⡀⠀⠀⠀⠀',
        '⠀⠀⠀⠀⠘⢄⣀⠀⠈⠡⡒⢾⠂⠀⠀⠀⠀⠀⠀⠳⢄⡀⠀⠈⠓⣄⣳⠀⠀⠀',
        '⠀⠀⠀⠀⠀⠀⠀⠑⠢⠴⠊⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠲⣌⣢⢡⠉⠀⠀⠀',
    ]
]

// Colors for different hedgehogs - one of each
const hedgehogColors = [
    'yellow',
    'cyan', 
    'magenta',
    'green',
    'blue',
    'red',
]

function getHedgehogDimensions(frameType: number): { width: number; height: number } {
    const frame = hedgehogFrames[frameType]
    if (!frame || frame.length === 0) {
        return { width: 36, height: 4 }
    }
    
    const height = frame.length
    const width = Math.max(...frame.map(line => line.length))
    return { width, height }
}

function createHedgehog(terminalWidth: number, terminalHeight: number, index: number, existingHedgehogs: Hedgehog[] = []): Hedgehog {
    // Randomly select a frame type for this hedgehog
    const frameType = Math.floor(Math.random() * hedgehogFrames.length)
    const dimensions = getHedgehogDimensions(frameType)
    
    const bannerHeight = 15 // Reserve space for banner + 2 line padding
    
    let attempts = 0
    let x: number, y: number
    
    // Try to find a non-colliding position below the banner
    do {
        x = Math.random() * (terminalWidth - dimensions.width)
        y = bannerHeight + Math.random() * (terminalHeight - dimensions.height - bannerHeight)
        attempts++
    } while (attempts < 50 && wouldCollide(x, y, dimensions, existingHedgehogs))
    
    return {
        x,
        y,
        direction: Math.random() > 0.5 ? 1 : -1,
        frameType,
        animationFrame: 0, // Start with first animation frame
        color: hedgehogColors[index % hedgehogColors.length],
        width: dimensions.width,
        height: dimensions.height,
    }
}

function wouldCollide(x: number, y: number, dimensions: { width: number; height: number }, existingHedgehogs: Hedgehog[]): boolean {
    for (const other of existingHedgehogs) {
        // Check if rectangles overlap with some padding
        const padding = 5
        if (x < other.x + other.width + padding &&
            x + dimensions.width + padding > other.x &&
            y < other.y + other.height + padding &&
            y + dimensions.height + padding > other.y) {
            return true
        }
    }
    return false
}

function getColorFunction(colorName: string): (text: string) => string {
    const colorMap: Record<string, (text: string) => string> = {
        yellow: chalk.yellow,
        cyan: chalk.cyan,
        magenta: chalk.magenta,
        green: chalk.green,
        blue: chalk.blue,
        red: chalk.red,
    }
    return colorMap[colorName] || chalk.white
}

function flipHedgehog(lines: string[]): string[] {
    return lines.map(line => {
        // Simple character replacement for flipping
        return line
            .split('')
            .reverse()
            .join('')
            .replace(/\//g, 'TEMP_SLASH')
            .replace(/\\/g, '/')
            .replace(/TEMP_SLASH/g, '\\')
            .replace(/\(/g, 'TEMP_PAREN')
            .replace(/\)/g, '(')
            .replace(/TEMP_PAREN/g, ')')
    })
}

function drawHedgehogs(hedgehogs: Hedgehog[], terminalWidth: number, terminalHeight: number): void {
    // Clear screen
    console.clear()
    
    // ASCII banner - shorter version that fits better
    const bannerLines = [
        '',
        '',
        '██   ██ ███████ ██████  ██   ██ ███████ ██   ██  ██████   ██████  ',
        '██   ██ ██      ██   ██ ██   ██ ██      ██   ██ ██    ██ ██       ',
        '███████ █████   ██   ██ ███████ █████   ███████ ██    ██ ██   ███ ',
        '██   ██ ██      ██   ██ ██   ██ ██      ██   ██ ██    ██ ██    ██ ',
        '██   ██ ███████ ██████  ██   ██ ███████ ██   ██  ██████   ██████  ',
        '',
        '███    ███  ██████  ██████  ███████      ██████  ███    ██ ',
        '████  ████ ██    ██ ██   ██ ██          ██    ██ ████   ██ ',
        '██ ████ ██ ██    ██ ██   ██ █████       ██    ██ ██ ██  ██ ',
        '██  ██  ██ ██    ██ ██   ██ ██          ██    ██ ██  ██ ██ ',
        '██      ██  ██████  ██████  ███████      ██████  ██   ████ '
    ]
    
    // Create empty screen buffer
    const screen: string[][] = []
    for (let i = 0; i < terminalHeight; i++) {
        screen[i] = new Array(terminalWidth).fill(' ')
    }
    
    // Draw banner centered at the top
    for (let i = 0; i < bannerLines.length && i < terminalHeight; i++) {
        const line = bannerLines[i]
        const startX = Math.max(0, Math.floor((terminalWidth - line.length) / 2))
        
        for (let j = 0; j < line.length && startX + j < terminalWidth; j++) {
            if (line[j] !== ' ') {
                screen[i][startX + j] = line[j]
            }
        }
    }
    
    // Draw each hedgehog
    for (const hedgehog of hedgehogs) {
        const colorFn = getColorFunction(hedgehog.color)
        
        // Get the current frame for this hedgehog type
        let hedgehogLines = hedgehogFrames[hedgehog.frameType]
        
        // For frame types that support animation, we could alternate between variants
        // For now, just use the base frame
        
        // Flip horizontally if moving left
        if (hedgehog.direction === -1) {
            hedgehogLines = flipHedgehog(hedgehogLines)
        }
        
        // Draw hedgehog onto screen buffer
        for (let lineIndex = 0; lineIndex < hedgehogLines.length; lineIndex++) {
            const y = Math.floor(hedgehog.y) + lineIndex
            if (y >= 0 && y < terminalHeight) {
                const line = hedgehogLines[lineIndex]
                for (let charIndex = 0; charIndex < line.length; charIndex++) {
                    const x = Math.floor(hedgehog.x) + charIndex
                    if (x >= 0 && x < terminalWidth && line[charIndex] !== ' ') {
                        screen[y][x] = line[charIndex]
                    }
                }
            }
        }
    }
    
    // Render screen with colors - apply colors during drawing, not after
    for (let y = 0; y < terminalHeight; y++) {
        let line = ''
        
        for (let x = 0; x < terminalWidth; x++) {
            let char = screen[y][x]
            
            // Check if this position belongs to any hedgehog
            for (const hedgehog of hedgehogs) {
                const hedgehogY = Math.floor(hedgehog.y)
                const hedgehogX = Math.floor(hedgehog.x)
                
                if (y >= hedgehogY && y < hedgehogY + hedgehog.height &&
                    x >= hedgehogX && x < hedgehogX + hedgehog.width &&
                    char !== ' ') {
                    const colorFn = getColorFunction(hedgehog.color)
                    char = colorFn(char)
                    break
                }
            }
            
            line += char
        }
        
        console.log(line.trimEnd())
    }
}

function updateHedgehogs(hedgehogs: Hedgehog[], terminalWidth: number, terminalHeight: number): void {
    for (let i = 0; i < hedgehogs.length; i++) {
        const hedgehog = hedgehogs[i]
        
        // Calculate next position
        const nextX = hedgehog.x + hedgehog.direction * 2
        
        // Check collision with other hedgehogs
        const otherHedgehogs = hedgehogs.filter((_, index) => index !== i)
        const wouldCollideWithOthers = wouldCollide(nextX, hedgehog.y, hedgehog, otherHedgehogs)
        
        // Bounce off walls or other hedgehogs - ensure we stay within bounds
        if (nextX <= 0 || nextX + hedgehog.width >= terminalWidth || wouldCollideWithOthers) {
            hedgehog.direction *= -1
            // Move away from the collision point
            const moveAmount = 3
            if (nextX <= 0) {
                hedgehog.x = moveAmount
            } else if (nextX + hedgehog.width >= terminalWidth) {
                hedgehog.x = terminalWidth - hedgehog.width - moveAmount
            } else {
                // Move away from other hedgehog collision
                hedgehog.x = Math.max(moveAmount, Math.min(terminalWidth - hedgehog.width - moveAmount, hedgehog.x + hedgehog.direction * moveAmount))
            }
        } else {
            hedgehog.x = nextX
        }
        
        // Update animation frame (subtle animation cycle)
        hedgehog.animationFrame = (hedgehog.animationFrame + 1) % 4
    }
}

export async function runHedgehogMode(options: HedgehogOptions): Promise<void> {
    const { speed } = options
    // Limit count to available colors
    const count = Math.min(options.count, hedgehogColors.length)
    
    // Get terminal size
    const terminalWidth = process.stdout.columns || 80
    const terminalHeight = process.stdout.rows || 24
    
    // Create hedgehogs - one of each color, avoiding collisions
    const hedgehogs: Hedgehog[] = []
    for (let i = 0; i < count; i++) {
        hedgehogs.push(createHedgehog(terminalWidth, terminalHeight, i, hedgehogs))
    }
    
    console.log(chalk.green('🦔 Hedgehog Mode Activated! Press Ctrl+C to exit 🦔'))
    console.log('')
    
    // Hide cursor
    process.stdout.write('\x1B[?25l')
    
    // Handle cleanup on exit
    process.on('SIGINT', () => {
        console.clear()
        // Show cursor
        process.stdout.write('\x1B[?25h')
        console.log(chalk.yellow('👋 Thanks for watching the hedgehogs! 🦔'))
        process.exit(0)
    })
    
    // Animation loop
    while (true) {
        drawHedgehogs(hedgehogs, terminalWidth, terminalHeight)
        updateHedgehogs(hedgehogs, terminalWidth, terminalHeight)
        
        // Wait for next frame
        await new Promise(resolve => setTimeout(resolve, speed))
    }
}