# Flox CUDA Development Guide

## Prerequisites & Authentication

- Sign up for early access at https://flox.dev
- Authenticate with `flox auth login`
- **Linux-only**: CUDA packages only work on `["aarch64-linux", "x86_64-linux"]`
- All CUDA packages are prefixed with `flox-cuda/` in the catalog
- **No macOS support**: Use Metal alternatives on Darwin

## Core Commands

```bash
# Search for CUDA packages
flox search cudatoolkit --all | grep flox-cuda
flox search nvcc --all | grep 12_8

# Show available versions
flox show flox-cuda/cudaPackages.cudatoolkit

# Install CUDA packages
flox install flox-cuda/cudaPackages_12_8.cuda_nvcc
flox install flox-cuda/cudaPackages.cuda_cudart

# Verify installation
nvcc --version
nvidia-smi
```

## Package Discovery

```bash
# Search for CUDA toolkit
flox search cudatoolkit --all | grep flox-cuda

# Search for specific versions
flox search nvcc --all | grep 12_8

# Show all available versions
flox show flox-cuda/cudaPackages.cudatoolkit

# Search for CUDA libraries
flox search libcublas --all | grep flox-cuda
flox search cudnn --all | grep flox-cuda
```

## Essential CUDA Packages

| Package Pattern | Purpose | Example |
|-----------------|---------|---------|
| `cudaPackages_X_Y.cudatoolkit` | Main CUDA Toolkit | `cudaPackages_12_8.cudatoolkit` |
| `cudaPackages_X_Y.cuda_nvcc` | NVIDIA C++ Compiler | `cudaPackages_12_8.cuda_nvcc` |
| `cudaPackages.cuda_cudart` | CUDA Runtime API | `cuda_cudart` |
| `cudaPackages_X_Y.libcublas` | Linear algebra | `cudaPackages_12_8.libcublas` |
| `cudaPackages_X_Y.libcufft` | Fast Fourier Transform | `cudaPackages_12_8.libcufft` |
| `cudaPackages_X_Y.libcurand` | Random number generation | `cudaPackages_12_8.libcurand` |
| `cudaPackages_X_Y.cudnn_9_11` | Deep neural networks | `cudaPackages_12_8.cudnn_9_11` |
| `cudaPackages_X_Y.nccl` | Multi-GPU communication | `cudaPackages_12_8.nccl` |

## Critical: Conflict Resolution

**CUDA packages have LICENSE file conflicts requiring explicit priorities:**

```toml
[install]
cuda_nvcc.pkg-path = "flox-cuda/cudaPackages_12_8.cuda_nvcc"
cuda_nvcc.systems = ["aarch64-linux", "x86_64-linux"]
cuda_nvcc.priority = 1                    # Highest priority

cuda_cudart.pkg-path = "flox-cuda/cudaPackages.cuda_cudart"
cuda_cudart.systems = ["aarch64-linux", "x86_64-linux"]
cuda_cudart.priority = 2

cudatoolkit.pkg-path = "flox-cuda/cudaPackages_12_8.cudatoolkit"
cudatoolkit.systems = ["aarch64-linux", "x86_64-linux"]
cudatoolkit.priority = 3                  # Lower for LICENSE conflicts

gcc.pkg-path = "gcc"
gcc-unwrapped.pkg-path = "gcc-unwrapped"  # For libstdc++
gcc-unwrapped.priority = 5
```

## CUDA Version Selection

### CUDA 12.x (Current)

```toml
[install]
cuda_nvcc.pkg-path = "flox-cuda/cudaPackages_12_8.cuda_nvcc"
cuda_nvcc.priority = 1
cuda_nvcc.systems = ["aarch64-linux", "x86_64-linux"]

cudatoolkit.pkg-path = "flox-cuda/cudaPackages_12_8.cudatoolkit"
cudatoolkit.priority = 3
cudatoolkit.systems = ["aarch64-linux", "x86_64-linux"]
```

### CUDA 11.x (Legacy Support)

```toml
[install]
cuda_nvcc.pkg-path = "flox-cuda/cudaPackages_11_8.cuda_nvcc"
cuda_nvcc.priority = 1
cuda_nvcc.systems = ["aarch64-linux", "x86_64-linux"]

cudatoolkit.pkg-path = "flox-cuda/cudaPackages_11_8.cudatoolkit"
cudatoolkit.priority = 3
cudatoolkit.systems = ["aarch64-linux", "x86_64-linux"]
```

## Cross-Platform GPU Development

CUDA does not exist on macOS, so the primary shape for a CUDA environment
is to LIMIT it to Linux at the environment level:

```toml
[options]
systems = ["x86_64-linux", "aarch64-linux"]
```

When the team also develops on Apple-silicon Macs, add a CPU fallback
instead (Linux gets CUDA, macOS gets CPU):

```toml
[install]
## CUDA packages (Linux only)
cuda-pytorch.pkg-path = "flox-cuda/python3Packages.torch"
cuda-pytorch.systems = ["x86_64-linux", "aarch64-linux"]
cuda-pytorch.priority = 1

## Non-CUDA fallback (Apple-silicon macOS)
pytorch.pkg-path = "python313Packages.pytorch"
pytorch.systems = ["aarch64-darwin"]
pytorch.priority = 6                     # Lower priority
```

## GPU Detection Pattern

**Dynamic CPU/GPU package installation in hooks:**

```bash
setup_gpu_packages() {
  venv="$FLOX_ENV_CACHE/venv"

  if [ ! -f "$FLOX_ENV_CACHE/.deps_installed" ]; then
    if lspci 2>/dev/null | grep -E 'NVIDIA|AMD' > /dev/null; then
      echo "GPU detected, installing CUDA packages"
      uv pip install --python "$venv/bin/python" \
        torch torchvision --index-url https://download.pytorch.org/whl/cu129
    else
      echo "No GPU detected, installing CPU packages"
      uv pip install --python "$venv/bin/python" \
        torch torchvision --index-url https://download.pytorch.org/whl/cpu
    fi
    touch "$FLOX_ENV_CACHE/.deps_installed"
  fi
}
```

## Complete CUDA Environment Examples

### Basic CUDA Development

```toml
[install]
cuda_nvcc.pkg-path = "flox-cuda/cudaPackages_12_8.cuda_nvcc"
cuda_nvcc.priority = 1
cuda_nvcc.systems = ["aarch64-linux", "x86_64-linux"]

cuda_cudart.pkg-path = "flox-cuda/cudaPackages.cuda_cudart"
cuda_cudart.priority = 2
cuda_cudart.systems = ["aarch64-linux", "x86_64-linux"]

gcc.pkg-path = "gcc"
gcc-unwrapped.pkg-path = "gcc-unwrapped"
gcc-unwrapped.priority = 5

[vars]
CUDA_VERSION = "12.8"
CUDA_HOME = "$FLOX_ENV"

[hook]
on-activate = '''
  echo "CUDA $CUDA_VERSION environment ready" >&2
  echo "nvcc: $(nvcc --version | grep release)" >&2
'''
```

### Deep Learning with PyTorch

```toml
[install]
cuda_nvcc.pkg-path = "flox-cuda/cudaPackages_12_8.cuda_nvcc"
cuda_nvcc.priority = 1
cuda_nvcc.systems = ["aarch64-linux", "x86_64-linux"]

cuda_cudart.pkg-path = "flox-cuda/cudaPackages.cuda_cudart"
cuda_cudart.priority = 2
cuda_cudart.systems = ["aarch64-linux", "x86_64-linux"]

libcublas.pkg-path = "flox-cuda/cudaPackages_12_8.libcublas"
libcublas.priority = 2
libcublas.systems = ["aarch64-linux", "x86_64-linux"]

cudnn.pkg-path = "flox-cuda/cudaPackages_12_8.cudnn_9_11"
cudnn.priority = 2
cudnn.systems = ["aarch64-linux", "x86_64-linux"]

python313Full.pkg-path = "python313Full"
uv.pkg-path = "uv"
gcc-unwrapped.pkg-path = "gcc-unwrapped"
gcc-unwrapped.priority = 5

[vars]
CUDA_VERSION = "12.8"
PYTORCH_CUDA_ALLOC_CONF = "max_split_size_mb:128"

[hook]
on-activate = '''
  setup_pytorch_cuda() {
    venv="$FLOX_ENV_CACHE/venv"

    if [ ! -d "$venv" ]; then
      uv venv "$venv" --python python3
    fi

    if [ -f "$venv/bin/activate" ]; then
      source "$venv/bin/activate"
    fi

    if [ ! -f "$FLOX_ENV_CACHE/.deps_installed" ]; then
      uv pip install --python "$venv/bin/python" \
        torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/cu129
      touch "$FLOX_ENV_CACHE/.deps_installed"
    fi
  }

  setup_pytorch_cuda
'''
```

### TensorFlow with CUDA

```toml
[install]
cuda_nvcc.pkg-path = "flox-cuda/cudaPackages_12_8.cuda_nvcc"
cuda_nvcc.priority = 1
cuda_nvcc.systems = ["aarch64-linux", "x86_64-linux"]

cuda_cudart.pkg-path = "flox-cuda/cudaPackages.cuda_cudart"
cuda_cudart.priority = 2
cuda_cudart.systems = ["aarch64-linux", "x86_64-linux"]

cudnn.pkg-path = "flox-cuda/cudaPackages_12_8.cudnn_9_11"
cudnn.priority = 2
cudnn.systems = ["aarch64-linux", "x86_64-linux"]

python313Full.pkg-path = "python313Full"
uv.pkg-path = "uv"

[hook]
on-activate = '''
  setup_tensorflow() {
    venv="$FLOX_ENV_CACHE/venv"
    [ ! -d "$venv" ] && uv venv "$venv" --python python3
    [ -f "$venv/bin/activate" ] && source "$venv/bin/activate"

    if [ ! -f "$FLOX_ENV_CACHE/.tf_installed" ]; then
      uv pip install --python "$venv/bin/python" tensorflow[and-cuda]
      touch "$FLOX_ENV_CACHE/.tf_installed"
    fi
  }

  setup_tensorflow
'''
```

### Multi-GPU Development

```toml
[install]
cuda_nvcc.pkg-path = "flox-cuda/cudaPackages_12_8.cuda_nvcc"
cuda_nvcc.priority = 1
cuda_nvcc.systems = ["aarch64-linux", "x86_64-linux"]

nccl.pkg-path = "flox-cuda/cudaPackages_12_8.nccl"
nccl.priority = 2
nccl.systems = ["aarch64-linux", "x86_64-linux"]

libcublas.pkg-path = "flox-cuda/cudaPackages_12_8.libcublas"
libcublas.priority = 2
libcublas.systems = ["aarch64-linux", "x86_64-linux"]

[vars]
CUDA_VISIBLE_DEVICES = "0,1,2,3"  # All GPUs
NCCL_DEBUG = "INFO"
```

## Modular CUDA Environments

### Base CUDA Environment

```toml
# team/cuda-base
[install]
cuda_nvcc.pkg-path = "flox-cuda/cudaPackages_12_8.cuda_nvcc"
cuda_nvcc.priority = 1
cuda_nvcc.systems = ["aarch64-linux", "x86_64-linux"]

cuda_cudart.pkg-path = "flox-cuda/cudaPackages.cuda_cudart"
cuda_cudart.priority = 2
cuda_cudart.systems = ["aarch64-linux", "x86_64-linux"]

gcc.pkg-path = "gcc"
gcc-unwrapped.pkg-path = "gcc-unwrapped"
gcc-unwrapped.priority = 5

[vars]
CUDA_VERSION = "12.8"
CUDA_HOME = "$FLOX_ENV"
```

### CUDA Math Libraries

```toml
# team/cuda-math
[include]
environments = [{ remote = "team/cuda-base" }]

[install]
libcublas.pkg-path = "flox-cuda/cudaPackages_12_8.libcublas"
libcublas.priority = 2
libcublas.systems = ["aarch64-linux", "x86_64-linux"]

libcufft.pkg-path = "flox-cuda/cudaPackages_12_8.libcufft"
libcufft.priority = 2
libcufft.systems = ["aarch64-linux", "x86_64-linux"]

libcurand.pkg-path = "flox-cuda/cudaPackages_12_8.libcurand"
libcurand.priority = 2
libcurand.systems = ["aarch64-linux", "x86_64-linux"]
```

### CUDA Debugging Tools

```toml
# team/cuda-debug
[install]
cuda-gdb.pkg-path = "flox-cuda/cudaPackages_12_8.cuda-gdb"
cuda-gdb.systems = ["aarch64-linux", "x86_64-linux"]

nsight-systems.pkg-path = "flox-cuda/cudaPackages_12_8.nsight-systems"
nsight-systems.systems = ["aarch64-linux", "x86_64-linux"]

[vars]
CUDA_LAUNCH_BLOCKING = "1"  # Synchronous kernel launches for debugging
```

### Layer for Development

```bash
# Base CUDA environment
flox activate -r team/cuda-base

# Add debugging tools when needed
flox activate -r team/cuda-base -- flox activate -r team/cuda-debug
```

## Testing CUDA Installation

### Verify CUDA Compiler

```bash
nvcc --version
```

### Check GPU Availability

```bash
nvidia-smi
```

### Compile Test Program

```bash
cat > hello_cuda.cu << 'EOF'
#include <stdio.h>

__global__ void hello() {
    printf("Hello from GPU!\n");
}

int main() {
    hello<<<1,1>>>();
    cudaDeviceSynchronize();
    return 0;
}
EOF

nvcc hello_cuda.cu -o hello_cuda
./hello_cuda
```

### Test PyTorch CUDA

```python
import torch
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"CUDA version: {torch.version.cuda}")
print(f"GPU count: {torch.cuda.device_count()}")
if torch.cuda.is_available():
    print(f"GPU name: {torch.cuda.get_device_name(0)}")
```

## Best Practices

### Always Use Priority Values
CUDA packages have predictable conflicts - assign explicit priorities

### Version Consistency
Use specific versions (e.g., `_12_8`) for reproducibility. Don't mix CUDA versions.

### Modular Design
Split base CUDA, math libs, and debugging into separate environments for flexibility

### Test Compilation
Verify `nvcc hello.cu -o hello` works after setup

### Platform Constraints
Always include `systems = ["aarch64-linux", "x86_64-linux"]`

### Memory Management
Set appropriate CUDA memory allocator configs:
```toml
[vars]
PYTORCH_CUDA_ALLOC_CONF = "max_split_size_mb:128"
CUDA_LAUNCH_BLOCKING = "0"  # Async by default
```

## Common CUDA Gotchas

### CUDA Toolkit ≠ Complete Toolkit
The cudatoolkit package doesn't include all libraries. Add what you need:
- libcublas for linear algebra
- libcufft for FFT
- cudnn for deep learning

### License Conflicts
Every CUDA package may need explicit priority due to LICENSE file conflicts

### No macOS Support
CUDA is Linux-only. Use Metal-accelerated packages on Darwin when available

### Version Mixing
Don't mix CUDA versions. Use consistent `_X_Y` suffixes across all CUDA packages

### Python Virtual Environments
CUDA Python packages (PyTorch, TensorFlow) should be installed in venv with correct CUDA version

### Driver Requirements
Ensure NVIDIA driver supports your CUDA version. Check with `nvidia-smi`

## Troubleshooting

### CUDA Not Found

```bash
# Check CUDA_HOME
echo $CUDA_HOME

# Check nvcc
which nvcc
nvcc --version

# Check library paths
echo $LD_LIBRARY_PATH
```

### PyTorch Not Using GPU

```python
import torch
print(torch.cuda.is_available())  # Should be True
print(torch.version.cuda)         # Should match your CUDA version

# If False, reinstall with correct CUDA version
# uv pip install torch --index-url https://download.pytorch.org/whl/cu129
```

### Compilation Errors

```bash
# Check gcc/g++ version
gcc --version
g++ --version

# Ensure gcc-unwrapped is installed
flox list | grep gcc-unwrapped

# Check include paths
echo $CPATH
echo $LIBRARY_PATH
```

### Runtime Errors

```bash
# Check GPU visibility
echo $CUDA_VISIBLE_DEVICES

# Check for GPU
nvidia-smi

# Run with debug output
CUDA_LAUNCH_BLOCKING=1 python my_script.py
```

