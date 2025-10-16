const express = require('express');
const app = express();
const port = 3000;

// Fake data for tasks
const tasks = [
  {
    id: 1,
    description: 'Complete monthly financial report'
  },
  {
    id: 2,
    description: 'Plan team building activity'
  },
  {
    id: 3,
    description: 'Update project documentation'
  }
];

app.get('/search', (req, res) => {
  // Retrieve the query parameter
  const query = req.query.query?.toLowerCase() || '';

  // Filter tasks based on the query
  const filteredTasks = tasks.filter(task => task.description.toLowerCase().includes(query));

  res.json(filteredTasks);
});

app.listen(port, () => {
  console.log(`Server running on port ${port}`);
});