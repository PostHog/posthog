FROM python:3.11-slim

# Install required system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install \
    chdb>=3.2.0 \
    requests \
    pandas

# Create test directory
WORKDIR /test

# Copy the test script
COPY test_chdb_v25_compatibility.py .

# Make the script executable
RUN chmod +x test_chdb_v25_compatibility.py

# Set the default command
CMD ["python", "test_chdb_v25_compatibility.py"] 