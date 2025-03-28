import { OrbitControls, useGLTF } from '@react-three/drei'
import { Canvas, useThree } from '@react-three/fiber'
import { useEffect, useRef } from 'react'
import * as THREE from 'three'

//
// // @ts-expect-error
// import glb from './crt_tv.glb'
//
// function Model(): JSX.Element {
//     const { scene } = useGLTF(glb) // automatically uses a GLTFLoader
//     return <primitive object={scene} />
// }
//
// export function CrtDashboard(): JSX.Element {
//     return (
//         <div style={{ width: '100vw', height: '100vh' }}>
//             <Canvas camera={{ position: [0, 0, 5] }}>
//                 <ambientLight />
//                 <pointLight position={[10, 10, 10]} />
//                 <Model url="/path/to/model.glb" />
//             </Canvas>
//         </div>
//     )
// }
import glb from './crt_tv.glb'
//
// function CrtTV() {
//     const { scene } = useGLTF(glb)
//     const groupRef = useRef<THREE.Group>(null!)
//
//     // Step 2 (and 3 & 4) goes in a useEffect to run once after we have the model
//     useEffect(() => {
//         if (!scene || !groupRef.current) {
//             return
//         }
//
//         // Add the loaded glTF scene to our group
//         groupRef.current.add(scene)
//
//         // Step 2: Create a bounding box (from the model's scene)
//         const box = new THREE.Box3().setFromObject(scene)
//
//         // Step 3: Get its size and center
//         const size = new THREE.Vector3()
//         const center = new THREE.Vector3()
//         box.getSize(size)
//         box.getCenter(center)
//
//         // Step 4: Position the model so it's centered at (0,0,0),
//         // or adjust how you want it in the scene:
//         // offset by negative center so model is around the origin
//         scene.position.x = scene.position.x - center.x
//         scene.position.y = scene.position.y - center.y
//         scene.position.z = scene.position.z - center.z
//
//         // Optionally, you can scale or do other transformations here
//     }, [scene])
//
//     return <group ref={groupRef} />
// }
//
// export function CrtDashboard(): JSX.Element | null {
//     const controlsRef = useRef<any>(null)
//     ;(window as any).controlsRef = controlsRef
//     return (
//         <Canvas style={{ width: 400, height: 400 }}>
//             <ambientLight />
//             <pointLight position={[10, 10, 10]} />
//             <Model />
//             <OrbitControls enablePan={true} enableZoom={true} enableRotate={true} ref={controlsRef} />
//         </Canvas>
//     )
// }

function CrtTV(): JSX.Element {
    const scenes = useGLTF(glb)
    const scene = Array.isArray(scenes) ? scenes[0].scene : scenes.scene
    console.log({ scene })

    useEffect(() => {
        // 1. Create the canvas + texture
        const canvas = document.createElement('canvas')
        canvas.width = 1024
        canvas.height = 512
        const ctx = canvas.getContext('2d')
        if (!ctx) {
            return
        }

        ctx.fillStyle = '#f00'
        ctx.fillRect(0, 0, canvas.width, canvas.height)
        ctx.fillStyle = '#ff0'
        ctx.font = '48px sans-serif'
        ctx.fillText('Analytics Dashboard', 100, 100)

        const texture = new THREE.CanvasTexture(canvas)

        // 2. Traverse the loaded model to find the screen
        scene.traverse((obj) => {
            console.log({ obj })
            if (obj.type === 'Mesh' && obj.parent?.name === 'Screen') {
                console.log('found screen')
                obj.material.map = texture
                obj.material.needsUpdate = true
            }
        })
    }, [scene])

    return <primitive object={scene} />
}

function Scene(): JSX.Element {
    const { camera, gl } = useThree()
    const tvRef = useRef<THREE.Group>(null!)

    useEffect(() => {
        if (!tvRef.current) {
            return
        }

        // 1. bounding box
        const box = new THREE.Box3().setFromObject(tvRef.current)
        const sphere = new THREE.Sphere()
        box.getBoundingSphere(sphere)

        // 2. compute distance
        const radius = sphere.radius
        const fov = camera.fov * (Math.PI / 180)
        const distance = radius / Math.sin(fov / 2)

        // 3. set camera
        camera.position.set(sphere.center.x, sphere.center.y, sphere.center.z + distance * 1.2) // 1.2 = just to back up a bit more
        camera.lookAt(sphere.center.x, sphere.center.y, sphere.center.z)

        // 4. optionally update the projection matrix
        camera.updateProjectionMatrix()
    }, [camera])

    return (
        <>
            <OrbitControls />
            <group ref={tvRef} rotation={[0, Math.PI, 0]}>
                <CrtTV />
            </group>
        </>
    )
}

export function CrtDashboard() {
    return (
        <Canvas style={{ width: 800, height: 800 }}>
            <ambientLight />
            <pointLight position={[10, 10, 10]} />
            <Scene />
        </Canvas>
    )
}
